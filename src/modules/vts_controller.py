"""
VTube Studio controller via pyvts com heartbeat, reconexão e estado real.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Dict, Optional

from src.config.config_loader import CONFIG
from src.modules.voice import speech_state

logger = logging.getLogger(__name__)

try:
    import pyvts

    PYVTS_OK = True
except ImportError:
    PYVTS_OK = False
    logger.warning("[VTS] pyvts não instalado. VTube Studio desabilitado.")


class VTSController:
    PLUGIN_NAME = "HanaAI"
    DEVELOPER_NAME = "Nakamura"
    TOKEN_PATH = os.path.abspath("data/vts_token.txt")
    STATE_PATH = os.path.abspath("data/vts_state.json")
    HEARTBEAT_SECONDS = 4.0
    ANIMATION_SECONDS = 0.05

    def __init__(self, host: str = "127.0.0.1", port: int = 8001, emotion_map: Dict[str, str] = None, signals=None):
        self.host = host
        self.port = int(port)
        self.emotion_map = emotion_map or {}
        self.signals = signals

        self.connected = False
        self.authenticated = False
        self.status = "idle"
        self.last_heartbeat_at = 0.0
        self.reconnect_attempts = 0
        self.tracking_mode = "injected_face_tracking"
        self.mouth_parameter = ""
        self.eye_parameters = ""
        self._last_error = ""
        self._last_expression = ""
        self._mouth_level = 0.0

        self._vts: Optional[object] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._supervisor_task: Optional[asyncio.Task] = None
        self._animation_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        self._available_hotkeys: list = []
        self._available_expressions: list = []
        self._available_parameters: list = []
        self._input_param_specs: Dict[str, Dict[str, float]] = {}
        self._input_param_ids: set[str] = set()
        self._model_param_ids: set[str] = set()
        self._supported_param_ids: set[str] = set()
        self._current_params: Dict[str, float] = {}
        self._tracking_active = True
        self._should_run = True
        self._lock = None # Criado dentro do loop asyncio
        self._write_state(status="idle")

    async def _request(self, request_msg):
        """Wrapper protegido por Lock para todos os pedidos ao VTube Studio."""
        if not self._vts or not self._lock:
            return None
        async with self._lock:
            try:
                response = await self._vts.request(request_msg)
                if isinstance(response, dict) and response.get("messageType") == "APIError":
                    data = response.get("data") or {}
                    message = data.get("message") or data.get("error") or response
                    raise RuntimeError(f"VTube Studio APIError: {message}")
                return response
            except Exception as e:
                logger.error("[VTS] Erro no request: %s", e)
                raise e

    def _state_payload(self, status: str | None = None, last_error: str | None = None):
        return {
            "status": status or self.status,
            "connected": self.connected,
            "authenticated": self.authenticated,
            "host": self.host,
            "port": self.port,
            "hotkeys": len(self._available_hotkeys),
            "expressions": len(self._available_expressions),
            "updated_at": time.time(),
            "last_heartbeat_at": self.last_heartbeat_at,
            "reconnect_attempts": self.reconnect_attempts,
            "mouth_parameter": self.mouth_parameter,
            "eye_parameters": self.eye_parameters,
            "tracking_mode": self.tracking_mode,
            "input_parameters": len(self._input_param_ids),
            "model_parameters": len(self._model_param_ids),
            "mouth_level": round(self._mouth_level, 3),
            "speaking": speech_state.is_speaking(self.signals),
            "last_error": last_error if last_error is not None else self._last_error,
            "last_expression": self._last_expression,
        }

    def _write_state(self, status: str | None = None, last_error: str | None = None):
        if status is not None:
            self.status = status
        if last_error is not None:
            self._last_error = last_error
        payload = self._state_payload(status=status, last_error=last_error)
        os.makedirs(os.path.dirname(self.STATE_PATH), exist_ok=True)
        with open(self.STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def start(self):
        if not PYVTS_OK:
            self._write_state(status="error", last_error="pyvts não instalado")
            logger.error("[VTS] pyvts não está instalado. Execute: pip install pyvts")
            return False

        if self._thread and self._thread.is_alive():
            return True

        self._should_run = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="VTS-Controller")
        self._thread.start()
        return True

    def stop(self):
        self._should_run = False

        if self._loop and self._loop.is_running():
            if self._supervisor_task:
                self._loop.call_soon_threadsafe(self._supervisor_task.cancel)
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=4)

        self.connected = False
        self.authenticated = False
        self._write_state(status="stopped")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._lock = asyncio.Lock()
        self._supervisor_task = self._loop.create_task(self._supervisor_loop())
        try:
            self._loop.run_forever()
        except Exception as e:
            self.connected = False
            self.authenticated = False
            self._write_state(status="error", last_error=str(e))
            logger.error("[VTS] Erro fatal no loop: %s", e)
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                try:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
            try:
                self._loop.close()
            except Exception:
                pass

    async def _supervisor_loop(self):
        backoff = 1.0
        logger.info("[VTS] Supervisor loop iniciado.")
        while self._should_run:
            if not CONFIG.get("VTUBESTUDIO_ATIVO", False):
                self._write_state(status="disabled")
                await asyncio.sleep(2.0)
                continue

            try:
                logger.info("[VTS] Tentando conectar a %s:%s...", self.host, self.port)
                await self._connect_and_auth()
                await self._load_available_actions()
                self._detect_mouth_parameter()
                self.reconnect_attempts = 0
                self._write_state(status="ready", last_error="")
                backoff = 1.0

                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="VTS-heartbeat")
                self._animation_task = asyncio.create_task(self._animation_loop(), name="VTS-animation")

                done, pending = await asyncio.wait(
                    [self._heartbeat_task, self._animation_task],
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    exc = task.exception()
                    if exc:
                        raise exc

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.connected = False
                self.authenticated = False
                self.reconnect_attempts += 1
                self._write_state(status="reconnecting", last_error=str(e))
                logger.warning("[VTS] Conexão perdida, reconectando: %s", e)
                await self._safe_disconnect()
                if not self._should_run:
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15.0)
                continue
            finally:
                await self._safe_disconnect()

        self.connected = False
        self.authenticated = False
        self._write_state(status="stopped")
        if self._loop and self._loop.is_running():
            self._loop.stop()

    async def _connect_and_auth(self):
        self._write_state(status="connecting", last_error="")
        plugin_info = {
            "plugin_name": self.PLUGIN_NAME,
            "developer": self.DEVELOPER_NAME,
            "authentication_token_path": self.TOKEN_PATH,
        }
        api_info = {
            "version": "1.0",
            "name": "VTubeStudioPublicAPI",
            "host": self.host,
            "port": self.port,
        }

        self._vts = pyvts.vts(plugin_info=plugin_info, vts_api_info=api_info)
        
        try:
            logger.info("[VTS] Abrindo WebSocket em %s:%s...", self.host, self.port)
            await self._vts.connect()
        except Exception as e:
            logger.error("[VTS] Falha no WebSocket. VTube Studio aberto? API 8001 ON? : %s", e)
            raise e

        self.connected = True
        self._write_state(status="connected", last_error="")

        token = self._read_token_file()
        if token:
            try:
                # Na API atual, passamos o token no request de autenticação
                response = await self._request(self._vts.vts_request.authentication(token))
                if response and response.get("data", {}).get("authenticated"):
                    self.authenticated = True
                    self._vts.authentic_token = token
                    self._write_state(status="authenticated", last_error="")
                    logger.info("[VTS] Autenticado com token salvo.")
                    return
                else:
                    logger.warning("[VTS] Token salvo rejeitado pelo VTube Studio.")
                    token = None
            except Exception as e:
                logger.warning("[VTS] Erro ao usar token salvo: %s", e)
                token = None

        logger.info("[VTS] Solicitando autorização no VTube Studio (veja o popup no app)...")
        self._write_state(status="awaiting_auth", last_error="")
        
        # 1. Solicita Token (Gera popup no VTS)
        response_token = await self._request(self._vts.vts_request.authentication_token())
        token = response_token.get("data", {}).get("authenticationToken")

        if not token:
            raise RuntimeError("Token de autenticação não recebido. Você clicou em 'Allow'?")

        # 2. Autentica com o novo token
        response_auth = await self._request(self._vts.vts_request.authentication(token))
        if response_auth and response_auth.get("data", {}).get("authenticated"):
            self._write_token_file(token)
            self._vts.authentic_token = token
            self.authenticated = True
            self._write_state(status="authenticated", last_error="")
            logger.info("[VTS] Autenticado com novo token.")
        else:
            raise RuntimeError("Falha na autenticação mesmo com novo token.")

    def _read_token_file(self):
        if not os.path.exists(self.TOKEN_PATH):
            return None
        try:
            with open(self.TOKEN_PATH, "r", encoding="utf-8") as f:
                return f.read().strip() or None
        except Exception:
            return None

    def _write_token_file(self, token: str):
        os.makedirs(os.path.dirname(self.TOKEN_PATH), exist_ok=True)
        with open(self.TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(str(token))

    @staticmethod
    def _safe_float(value, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _register_input_parameter(self, item) -> None:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("id") or "").strip()
            minimum = self._safe_float(item.get("min"), -1000000.0)
            maximum = self._safe_float(item.get("max"), 1000000.0)
            default = self._safe_float(item.get("defaultValue"), 0.0)
        else:
            name = str(item or "").strip()
            minimum = -1000000.0
            maximum = 1000000.0
            default = 0.0
            item = {"name": name, "min": minimum, "max": maximum, "defaultValue": default}

        if not name:
            return
        self._input_param_ids.add(name)
        self._supported_param_ids.add(name)
        self._input_param_specs[name] = {"min": minimum, "max": maximum, "default": default}
        self._available_parameters.append(item)

    def _register_model_parameter(self, item) -> None:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("id") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            self._model_param_ids.add(name)

    def _clamp_param_value(self, name: str, value: float) -> float:
        spec = self._input_param_specs.get(name, {})
        minimum = spec.get("min", -1000000.0)
        maximum = spec.get("max", 1000000.0)
        parsed = self._safe_float(value, spec.get("default", 0.0))
        return max(minimum, min(maximum, parsed))

    async def _load_available_actions(self):
        self._available_hotkeys = []
        self._available_expressions = []
        self._available_parameters = []
        self._input_param_specs = {}
        self._input_param_ids = set()
        self._model_param_ids = set()
        self._supported_param_ids = set()

        try:
            response = await self._request(self._vts.vts_request.requestHotKeyList())
            if response and "data" in response:
                self._available_hotkeys = response["data"].get("availableHotkeys", [])
        except Exception as e:
            logger.warning("[VTS] Erro ao carregar hotkeys: %s", e)

        try:
            # Em pyvts 0.3.3, usamos BaseRequest para ExpressionStateRequest
            response = await self._request(self._vts.vts_request.BaseRequest("ExpressionStateRequest", {}))
            if response and "data" in response:
                self._available_expressions = response["data"].get("expressions", [])
        except Exception as e:
            logger.warning("[VTS] Erro ao carregar expressões: %s", e)

        try:
            response = await self._request(self._vts.vts_request.requestTrackingParameterList())
            data = response.get("data", {}) if isinstance(response, dict) else {}
            for key in ("defaultParameters", "customParameters", "trackingParameters", "availableParameters", "parameters"):
                values = data.get(key)
                if isinstance(values, list):
                    for item in values:
                        self._register_input_parameter(item)
        except Exception as e:
            logger.warning("[VTS] Erro ao carregar parametros de tracking: %s", e)

        try:
            response = await self._request(self._vts.vts_request.BaseRequest("CurrentModelRequest", {}))
            data = response.get("data", {}) if isinstance(response, dict) else {}
            for key in ("modelParameters", "live2DParameters"):
                values = data.get(key)
                if isinstance(values, list):
                    for item in values:
                        self._register_model_parameter(item)
        except Exception as e:
            logger.debug("[VTS] Modelo atual sem lista de parametros Live2D: %s", e)
        
        if self._supported_param_ids:
            logger.info(
                "[VTS] %d parametros de tracking detectados: %s",
                len(self._supported_param_ids),
                list(self._supported_param_ids)[:20],
            )

    def _detect_mouth_parameter(self):
        priorities = [
            "MouthOpen",
            "VoiceVolumePlusMouthOpen",
            "VoiceVolume",
            "VoiceA",
        ]
        self.mouth_parameter = ""
        for candidate in priorities:
            if candidate in self._supported_param_ids:
                self.mouth_parameter = candidate
                break
        self.eye_parameters = ""
        if {"EyeOpenLeft", "EyeOpenRight"}.issubset(self._supported_param_ids):
            self.eye_parameters = "EyeOpenLeft,EyeOpenRight"

    async def _heartbeat_loop(self):
        while self._should_run and self.connected and self.authenticated:
            try:
                await self._request(self._vts.vts_request.requestHotKeyList())
                self.last_heartbeat_at = time.time()
                self._write_state(status="ready", last_error="")
            except Exception as e:
                raise RuntimeError(f"heartbeat falhou: {e}") from e
            await asyncio.sleep(self.HEARTBEAT_SECONDS)

    async def _animation_loop(self):
        import math
        import random

        t = 0.0
        target_x, target_y = 0.0, 0.0
        current_x, current_y = 0.0, 0.0
        gesture_until = 0.0
        gesture_side = "right"
        gesture_seed = 0.0

        while self._should_run and self.connected and self.authenticated:
            t += 0.05
            if random.random() < 0.04:
                target_x = random.uniform(-15, 15)
                target_y = random.uniform(-10, 10)

            current_x += (target_x - current_x) * 0.1
            current_y += (target_y - current_y) * 0.1
            angle_z = math.sin(t * 0.5) * 4
            is_speaking = speech_state.is_speaking(self.signals)

            eye_open = 1.0
            if t > 3.0 and random.random() < 0.012:
                eye_open = 0.0

            if is_speaking:
                syllable = (math.sin(t * 27.0) + 1.0) / 2.0
                micro = max(0.0, math.sin(t * 43.0 + 1.1)) ** 2.4
                phrase = 0.9 + ((math.sin(t * 3.4 + 0.5) + 1.0) / 2.0) * 0.12
                mouth_target = min(0.56, (0.055 + (syllable ** 1.18) * 0.34 + micro * 0.12) * phrase)
                response = 0.92 if mouth_target > self._mouth_level else 0.82
            else:
                mouth_target = 0.0
                response = 0.55

            self._mouth_level += (mouth_target - self._mouth_level) * response
            mouth_value = max(0.0, min(0.62, self._mouth_level))

            body_energy = 1.0 if is_speaking else 0.32
            body_angle_x = math.sin(t * 1.15) * 1.4 * body_energy
            body_angle_y = math.sin(t * 0.9 + 1.2) * 0.9 * body_energy
            body_angle_z = math.sin(t * 1.35 + 0.4) * 1.8 * body_energy
            body_position_y = math.sin(t * 1.4) * 0.035 * body_energy
            body_position_z = math.sin(t * 1.1 + 0.6) * 0.04 * body_energy
            face_position_y = math.sin(t * 1.6 + 0.2) * 0.22 * body_energy
            face_position_z = math.sin(t * 1.2 + 0.7) * 0.18 * body_energy
            brow_value = min(0.52, 0.08 + mouth_value * 0.42 + (0.05 * math.sin(t * 6.0) if is_speaking else 0.0))
            smile_value = 0.42 + (0.16 if is_speaking else 0.05) + math.sin(t * 1.8) * 0.035

            if is_speaking and t >= gesture_until and random.random() < 0.025:
                gesture_until = t + random.uniform(1.0, 1.8)
                gesture_side = "right" if random.random() < 0.62 else "left"
                gesture_seed = random.uniform(0.0, math.tau)
            gesture_active = is_speaking and t < gesture_until
            gesture_phase = math.sin((t + gesture_seed) * 8.0)
            hand_found = 1.0 if is_speaking else 0.0
            left_boost = 1.0 if gesture_active and gesture_side == "left" else 0.35
            right_boost = 1.0 if gesture_active and gesture_side == "right" else 0.45

            params = {
                "FaceAngleX": current_x,
                "FaceAngleY": current_y + (math.sin(t * 4) * 2.5 if is_speaking else 0.0),
                "FaceAngleZ": angle_z + (math.sin(t * 6) * 1.5 if is_speaking else 0.0),
                "FacePositionX": math.sin(t * 0.85) * 0.12 * body_energy,
                "FacePositionY": face_position_y,
                "FacePositionZ": face_position_z,
                "EyeOpenLeft": eye_open,
                "EyeOpenRight": eye_open,
                "EyeLeftX": current_x / 15.0,
                "EyeLeftY": current_y / 10.0,
                "EyeRightX": current_x / 15.0,
                "EyeRightY": current_y / 10.0,
                "MouthOpen": mouth_value,
                "MouthSmile": smile_value,
                "MouthX": math.sin(t * 13.0) * 0.05 * mouth_value if is_speaking else 0.0,
                "Brows": brow_value,
                "BrowLeftY": brow_value + (0.04 * math.sin(t * 7.0) if is_speaking else 0.0),
                "BrowRightY": brow_value + (0.04 * math.sin(t * 6.5 + 1.2) if is_speaking else 0.0),
                "CheekPuff": 0.02 + mouth_value * 0.06 if is_speaking else 0.0,
                "VoiceVolume": mouth_value,
                "VoiceVolumePlusMouthOpen": mouth_value,
                "VoiceFrequency": 0.55 + (math.sin(t * 13.0) * 0.08 if is_speaking else 0.0),
                "VoiceFrequencyPlusMouthSmile": 0.5 + (math.sin(t * 13.0) * 0.08 if is_speaking else 0.0),
                "VoiceA": mouth_value if is_speaking else 0.0,
                "VoiceI": max(0.0, math.sin(t * 19.0)) * mouth_value if is_speaking else 0.0,
                "VoiceU": max(0.0, math.sin(t * 13.0 + 1.0)) * mouth_value if is_speaking else 0.0,
                "VoiceE": max(0.0, math.sin(t * 17.0 + 2.0)) * mouth_value if is_speaking else 0.0,
                "VoiceO": max(0.0, math.sin(t * 11.0 + 3.0)) * mouth_value if is_speaking else 0.0,
                "VoiceSilence": 0.0 if is_speaking else 1.0,
                "MocopiBodyAngleX": body_angle_x,
                "MocopiBodyAngleY": body_angle_y,
                "MocopiBodyAngleZ": body_angle_z,
                "MocopiBodyPositionX": math.sin(t * 0.75) * 0.025 * body_energy,
                "MocopiBodyPositionY": body_position_y,
                "MocopiBodyPositionZ": body_position_z,
                "ControllerShoulderLeft": max(0.0, min(1.0, 0.18 + mouth_value * 0.22 + math.sin(t * 3.0) * 0.04)),
                "ControllerShoulderRight": max(0.0, min(1.0, 0.2 + mouth_value * 0.24 + math.sin(t * 3.4 + 0.7) * 0.04)),
                "HandLeftFound": hand_found,
                "HandRightFound": hand_found,
                "BothHandsFound": hand_found,
                "HandDistance": 3.4 + math.sin(t * 1.6) * 0.25 if is_speaking else 0.0,
                "HandLeftPositionX": 3.0 + math.sin(t * 1.7) * 0.18 if is_speaking else 0.0,
                "HandLeftPositionY": -1.8 + left_boost * (0.6 + gesture_phase * 0.35) if is_speaking else 0.0,
                "HandLeftPositionZ": 0.15 + left_boost * math.sin(t * 2.5 + 0.4) * 0.28 if is_speaking else 0.0,
                "HandRightPositionX": 7.0 + math.sin(t * 1.9 + 1.0) * 0.18 if is_speaking else 0.0,
                "HandRightPositionY": -1.7 + right_boost * (0.65 + gesture_phase * 0.38) if is_speaking else 0.0,
                "HandRightPositionZ": 0.15 + right_boost * math.sin(t * 2.7 + 1.1) * 0.28 if is_speaking else 0.0,
                "HandLeftAngleX": -10.0 + left_boost * math.sin(t * 4.6 + gesture_seed) * 18.0 if is_speaking else 0.0,
                "HandLeftAngleZ": -8.0 + left_boost * math.sin(t * 5.2 + 0.5) * 16.0 if is_speaking else 0.0,
                "HandRightAngleX": 10.0 + right_boost * math.sin(t * 4.9 + gesture_seed) * 18.0 if is_speaking else 0.0,
                "HandRightAngleZ": 8.0 + right_boost * math.sin(t * 5.0 + 1.2) * 16.0 if is_speaking else 0.0,
                "HandLeftOpen": 0.58 + left_boost * 0.22 if is_speaking else 0.0,
                "HandRightOpen": 0.62 + right_boost * 0.24 if is_speaking else 0.0,
            }
            await self._send_multi_parameters(params)
            await asyncio.sleep(self.ANIMATION_SECONDS)

    async def _send_multi_parameters(self, params: Dict[str, float]):
        supported = {
            key: self._clamp_param_value(key, value)
            for key, value in params.items()
            if key in self._supported_param_ids
        }
        if not supported:
            return

        request = self._vts.vts_request.requestSetMultiParameterValue(
            list(supported.keys()),
            list(supported.values()),
            face_found=True,
            mode="set",
        )
        await self._request(request)
        self._current_params.update(supported)

    async def _safe_disconnect(self):
        for task in (self._animation_task, self._heartbeat_task):
            if task and not task.done():
                task.cancel()
        self._animation_task = None
        self._heartbeat_task = None

        if self._vts:
            try:
                await self._vts.close()
            except Exception:
                pass
        self._vts = None
        self.connected = False
        self.authenticated = False

    def set_parameter(self, name: str, value: float):
        if not self.authenticated or not self._loop:
            return
        asyncio.run_coroutine_threadsafe(self._send_parameter(name, value), self._loop)

    async def _send_parameter(self, name: str, value: float):
        try:
            if name not in self._supported_param_ids:
                return
            value = self._clamp_param_value(name, value)
            request = self._vts.vts_request.requestSetParameterValue(name, value, face_found=True, mode="set")
            await self._request(request)
            self._current_params[name] = value
        except Exception as e:
            logger.error("[VTS] Erro ao definir parâmetro %s: %s", name, e)

    def trigger_emotion(self, emotion: str):
        if not self.authenticated or not self._loop:
            return
        hotkey_name = self.emotion_map.get(str(emotion or "").upper())
        if not hotkey_name:
            return
        asyncio.run_coroutine_threadsafe(self._send_hotkey(hotkey_name), self._loop)

    async def _send_hotkey(self, hotkey_name: str):
        hotkey_id = None
        for hk in self._available_hotkeys:
            if hk.get("name", "").lower() == hotkey_name.lower():
                hotkey_id = hk.get("hotkeyID")
                break

        try:
            if hotkey_id:
                await self._request(self._vts.vts_request.requestTriggerHotKey(hotkey_id))
                self._last_expression = hotkey_name
                self._write_state(status="ready", last_error="")
                return
            await self._send_expression(hotkey_name)
        except Exception as e:
            logger.error("[VTS] Erro ao disparar hotkey '%s': %s", hotkey_name, e)

    async def _send_expression(self, expression_name: str):
        try:
            for expr in self._available_expressions:
                file_name = expr.get("name", "")
                if expression_name.lower() in file_name.lower():
                    request = self._vts.vts_request.requestExpressionActivation(file_name, active=True)
                    await self._request(request)
                    self._last_expression = file_name
                    self._write_state(status="ready", last_error="")
                    asyncio.create_task(self._delayed_reset(5, express_file=file_name))
                    return
        except Exception as e:
            logger.error("[VTS] Erro ao ativar expressão: %s", e)

    async def _delayed_reset(self, delay: int, express_file: str = None):
        await asyncio.sleep(delay)
        try:
            if express_file:
                request = self._vts.vts_request.requestExpressionActivation(express_file, active=False)
                await self._vts.request(request)
        except Exception:
            pass

    def get_anatomy_detailed(self) -> str:
        details = []
        if self._available_expressions:
            details.append(f"- Expressoes: {', '.join([e.get('name') for e in self._available_expressions])}")
        if self.mouth_parameter:
            details.append(f"- Parametro de boca: {self.mouth_parameter}")

        p_list = []
        preferred = {
            "FaceAngleX",
            "FaceAngleY",
            "FaceAngleZ",
            "MouthOpen",
            "MouthSmile",
            "MouthX",
            "EyeOpenLeft",
            "EyeOpenRight",
            "EyeLeftX",
            "EyeLeftY",
            "EyeRightX",
            "EyeRightY",
            "VoiceVolume",
            "VoiceVolumePlusMouthOpen",
        }
        for p in self._available_parameters:
            if isinstance(p, dict):
                name = p.get("name") or p.get("id", "")
                min_val = p.get("min")
                max_val = p.get("max")
            else:
                name = str(p)
                min_val = "?"
                max_val = "?"
            if str(name) not in preferred:
                continue
            p_list.append(f"{name} ({min_val} a {max_val})")

        if p_list:
            details.append(f"- Parametros de tracking utilizaveis: {', '.join(p_list)}")

        return "\n".join(details)
