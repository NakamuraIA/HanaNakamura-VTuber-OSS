from __future__ import annotations

from typing import Any


def _browser_media_recorder_device() -> dict[str, Any]:
    """Return the browser-side microphone contract when backend enumeration is unavailable."""
    return {
        "id": "browser_default",
        "label": "Browser default microphone",
        "source": "browser_media_recorder",
        "isDefault": True,
        "available": True,
        "channels": None,
        "sampleRate": None,
    }


def list_input_devices() -> dict[str, Any]:
    """List backend-visible input devices without requiring a new audio dependency."""
    devices = [_browser_media_recorder_device()]
    backend_available = False
    backend_error = ""

    try:
        import sounddevice as sd  # type: ignore[import-not-found]

        default_input = None
        try:
            default_input = sd.default.device[0]
        except Exception:
            default_input = None

        for index, item in enumerate(sd.query_devices()):
            max_input_channels = int(item.get("max_input_channels") or 0)
            if max_input_channels <= 0:
                continue

            devices.append(
                {
                    "id": f"sounddevice:{index}",
                    "label": str(item.get("name") or f"Input device {index}"),
                    "source": "sounddevice",
                    "isDefault": index == default_input,
                    "available": True,
                    "channels": max_input_channels,
                    "sampleRate": item.get("default_samplerate"),
                }
            )
        backend_available = True
    except Exception as exc:
        backend_error = str(exc)

    return {
        "devices": devices,
        "backendEnumeration": {
            "available": backend_available,
            "optionalDependency": "sounddevice",
            "error": backend_error,
        },
        "recommendedCapture": "sounddevice",
    }


def list_output_devices() -> dict[str, Any]:
    """List backend-visible OUTPUT devices (playback) for the second voice output picker.

    Mirrors :func:`list_input_devices` but filters on ``max_output_channels`` — used by
    the "segunda saída de áudio" feature so the user can route Hana's TTS to a virtual
    cable (e.g. VB-Audio CABLE Input) on top of the local speakers.
    """
    devices: list[dict[str, Any]] = []
    backend_available = False
    backend_error = ""

    try:
        import sounddevice as sd  # type: ignore[import-not-found]

        try:
            default_output = sd.default.device[1]
        except Exception:
            default_output = None

        for index, item in enumerate(sd.query_devices()):
            max_output_channels = int(item.get("max_output_channels") or 0)
            if max_output_channels <= 0:
                continue
            devices.append(
                {
                    "id": f"sounddevice:{index}",
                    "label": str(item.get("name") or f"Output device {index}"),
                    "source": "sounddevice",
                    "isDefault": index == default_output,
                    "available": True,
                    "channels": max_output_channels,
                    "sampleRate": item.get("default_samplerate"),
                }
            )
        backend_available = True
    except Exception as exc:
        backend_error = str(exc)

    return {
        "devices": devices,
        "backendEnumeration": {
            "available": backend_available,
            "optionalDependency": "sounddevice",
            "error": backend_error,
        },
    }
