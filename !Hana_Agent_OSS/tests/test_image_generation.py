from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.vision.character_library import (
    compose_character_prompt,
    load_character_profile,
    parse_character_image_request,
    resolve_request_reference_paths,
)
from hana_agent_oss.modules.vision.image_gen import HanaImageGen, resolve_output_dir
from hana_agent_oss.modules.vision.image_service import (
    LAST_IMAGE_GENERATION_KEY,
    ImageOperationResult,
    ImageGenerationService,
    detect_character_id,
    infer_image_operation,
)
from hana_agent_oss.modules.vision.image_xml import extract_image_xml_actions, strip_image_xml_tags
from hana_agent_oss.providers.contracts import ProviderResponse


def test_save_image_from_response_accepts_inline_data_bytes(tmp_path: Path) -> None:
    generator = HanaImageGen(output_dir=str(tmp_path))
    part = SimpleNamespace(inline_data=SimpleNamespace(data=b"fake-png"))
    response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])

    filepath = generator._save_image_from_response(response, "Hana cyberpunk", prefix="gen")

    assert filepath is not None
    assert Path(filepath).read_bytes() == b"fake-png"


def test_save_image_from_response_accepts_inline_data_base64(tmp_path: Path) -> None:
    generator = HanaImageGen(output_dir=str(tmp_path))
    encoded = base64.b64encode(b"fake-png-b64").decode("ascii")
    part = SimpleNamespace(inlineData=SimpleNamespace(data=encoded))
    response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])

    filepath = generator._save_image_from_response(response, "Hana lab", prefix="gen")

    assert filepath is not None
    assert Path(filepath).read_bytes() == b"fake-png-b64"


def test_resolve_output_dir_uses_memory_portability_config(tmp_path: Path) -> None:
    memory = MemoryStore(db_path=tmp_path / "memory.sqlite3", events_path=tmp_path / "events.jsonl")
    output_dir = tmp_path / "custom-media"
    memory.set_setting("portabilidade_config", {"mediaOutputPath": str(output_dir)})

    resolved = resolve_output_dir(memory=memory)

    assert resolved == str(output_dir.resolve())
    assert output_dir.exists()


def test_character_profile_lookup_is_case_insensitive(tmp_path: Path) -> None:
    nyra_dir = tmp_path / "Nyra"
    nyra_dir.mkdir()
    (nyra_dir / "character.json").write_text(
        '{"display_name":"Nyra","identity_prompt":"x","negative_prompt":"","default_references":[],"reference_images":{}}',
        encoding="utf-8",
    )

    profile = load_character_profile("nyra", root_dir=str(tmp_path))

    assert profile.display_name == "Nyra"
    assert Path(profile.root_dir).name == "Nyra"


def test_multi_character_request_loads_aliases_and_references(tmp_path: Path) -> None:
    hana_dir = tmp_path / "hana"
    nyra_dir = tmp_path / "Nyra"
    shogun_dir = tmp_path / "Shogun"
    for folder in (hana_dir, nyra_dir, shogun_dir):
        folder.mkdir()
        (folder / "base.png").write_bytes(b"fake")
    (hana_dir / "character.json").write_text(
        '{"display_name":"Hana AM Operador","identity_prompt":"hana identity","negative_prompt":"bad hana","default_references":["base"],"reference_images":{"base":"base.png"}}',
        encoding="utf-8",
    )
    (nyra_dir / "character.json").write_text(
        '{"display_name":"Nyra","identity_prompt":"nyra identity","negative_prompt":"bad nyra","default_references":["base"],"reference_images":{"base":"base.png"}}',
        encoding="utf-8",
    )
    (shogun_dir / "character.json").write_text(
        '{"display_name":"Shogun","nickname":"shoggers","identity_prompt":"shogun identity","negative_prompt":"bad shogun","default_references":["base"],"reference_images":{"base":"base.png"}}',
        encoding="utf-8",
    )

    request = parse_character_image_request(
        {"characters": ["hana", "nyra", "shoggers"], "prompt": "Hana, Nyra, and Shogun drinking coffee together."},
        root_dir=str(tmp_path),
    )

    assert request.character_ids == ("hana", "nyra", "shogun")
    assert [profile.display_name for profile in request.profiles] == ["Hana AM Operador", "Nyra", "Shogun"]
    refs = resolve_request_reference_paths(request)
    assert len(refs) == 3
    assert all(Path(path).name == "base.png" for path in refs)
    final_prompt = compose_character_prompt(request)
    assert "multiple registered characters" in final_prompt
    assert "Identity rules for Nyra: nyra identity" in final_prompt


def test_missing_character_json_returns_clear_error(tmp_path: Path) -> None:
    (tmp_path / "nakamura").mkdir()

    try:
        parse_character_image_request({"character": "nakamura", "prompt": "Operador portrait"}, root_dir=str(tmp_path))
    except FileNotFoundError as exc:
        assert "Personagem visual nao cadastrado: nakamura" in str(exc)
    else:
        raise AssertionError("Expected missing Operador character.json to fail clearly")


def test_infer_image_operation_detects_generation_and_edit() -> None:
    assert infer_image_operation("gere uma imagem da Hana em um laboratorio cyberpunk", []) == "character_generate"
    assert infer_image_operation("queria uma imagem da Hana tomando cafe", []) == "character_generate"
    assert infer_image_operation("crie uma imagem de uma cidade neon", []) == "generate"
    assert infer_image_operation("mude o fundo dessa foto", [{"type": "image/png", "path": "x"}]) == "edit"
    assert infer_image_operation("edita essa imagem com luz neon", []) == "edit"


def test_character_detection_uses_character_json_aliases(tmp_path: Path) -> None:
    shogun_dir = tmp_path / "Shogun"
    shogun_dir.mkdir()
    (shogun_dir / "character.json").write_text(
        '{"display_name":"Shogun","nickname":"shoggers","identity_prompt":"x","negative_prompt":"","default_references":[],"reference_images":{}}',
        encoding="utf-8",
    )

    assert detect_character_id("gere uma imagem da Shogun", root_dir=str(tmp_path)) == "shogun"
    assert detect_character_id("faz uma arte da shoggers", root_dir=str(tmp_path)) == "shogun"
    assert infer_image_operation("gere uma imagem da Shogun", [], root_dir=str(tmp_path)) == "character_generate"


def test_self_reference_generation_targets_hana() -> None:
    assert detect_character_id("gere uma imagem sua") == "hana"
    assert infer_image_operation("gere uma imagem sua", []) == "character_generate"


def test_image_xml_parser_extracts_and_strips_tags() -> None:
    text = "Vou preparar. <gerar_imagem>A cyberpunk cat</gerar_imagem>"

    actions = extract_image_xml_actions(text)

    assert actions["gerar_imagem"] == ["A cyberpunk cat"]
    assert strip_image_xml_tags(text) == "Vou preparar."


def test_image_xml_parser_accepts_multi_character_payload() -> None:
    text = (
        "Vou preparar as duas juntas. "
        '<gerar_imagem_personagem>{"characters":["hana","nyra"],"prompt":"Hana and Nyra drinking coffee together."}</gerar_imagem_personagem>'
    )

    actions = extract_image_xml_actions(text)

    assert '"characters":["hana","nyra"]' in actions["gerar_imagem_personagem"][0]
    assert strip_image_xml_tags(text) == "Vou preparar as duas juntas."


def test_image_service_accepts_raw_multi_character_xml_payload(monkeypatch, tmp_path: Path) -> None:
    memory = MemoryStore(db_path=tmp_path / "memory.sqlite3", events_path=tmp_path / "events.jsonl")
    image_path = tmp_path / "hana_nyra.png"
    captured: dict[str, object] = {}

    def _fake_generate_character(self, payload):
        captured["payload"] = payload
        image_path.write_bytes(b"fake")
        return str(image_path)

    monkeypatch.setattr(HanaImageGen, "generate_character", _fake_generate_character)
    service = ImageGenerationService(memory=memory, output_dir=str(tmp_path))

    result = service.generate_character('{"characters":["hana","nova"],"prompt":"Hana and Nova drinking coffee together."}')

    assert result.ok is True
    assert captured["payload"] == {
        "characters": ["hana", "nova"],
        "prompt": "Hana and Nova drinking coffee together.",
        "mode": "scene",
    }
    last = memory.get_setting(LAST_IMAGE_GENERATION_KEY, {})
    assert last["character_ids"] == ["hana", "nova"]
    assert last["character_id"] == "hana, nova"
    assert "Identity rules for Nova" in last["final_prompt"]


def test_prompt_lookup_returns_last_image_prompt_without_generation(tmp_path: Path) -> None:
    memory = MemoryStore(db_path=tmp_path / "memory.sqlite3", events_path=tmp_path / "events.jsonl")
    memory.set_setting(
        LAST_IMAGE_GENERATION_KEY,
        {
            "operation": "character_generate",
            "user_prompt": "gera a Hana",
            "final_prompt": "Use references. Creative request: Hana no laboratorio.",
            "character_id": "hana",
            "saved_path": str(tmp_path / "hana.png"),
            "model": "gemini-3.1-flash-image-preview",
        },
    )
    service = ImageGenerationService(memory=memory, output_dir=str(tmp_path))

    # Feature disabled per user rules: no keyword gatilhos from user text that auto-dump previous image prompts.
    # _looks_like_prompt_lookup now always returns False to prevent side-effect triggers.
    response = service.prompt_lookup_response("me manda o prompt que voce usou", channel="voice")

    assert response is None  # disabled - no more auto triggers from phrases like "manda o prompt que voce usou"


def test_run_text_turn_executes_image_xml_and_returns_clean_text(monkeypatch, tmp_path: Path) -> None:
    from hana_agent_oss.api.services import chat as chat_service

    memory = MemoryStore(db_path=tmp_path / "memory.sqlite3", events_path=tmp_path / "events.jsonl")
    image_path = tmp_path / "cat.png"

    def _fake_provider(_request):
        return ProviderResponse(
            ok=True,
            text="Vou preparar essa imagem. <gerar_imagem>A cyberpunk cat drinking coffee</gerar_imagem>",
            meta={"nativeSearch": False},
        )

    def _fake_generate(self, prompt: str) -> ImageOperationResult:
        image_path.write_bytes(prompt.encode("utf-8"))
        return ImageOperationResult(
            ok=True,
            text="Imagem gerada pela Hana.",
            media=[{"type": "image", "url": "/api/media/image/cat.png", "status": "ready"}],
            saved_path=str(image_path),
        )

    monkeypatch.setattr(chat_service.PROVIDER_SELECTOR, "generate", _fake_provider)
    monkeypatch.setattr(ImageGenerationService, "generate", _fake_generate)

    result = __import__("asyncio").run(
        chat_service.run_text_turn(
            {"text": "gera uma imagem de gato", "provider": "gemini_api", "model": "gemini-3.5-flash"},
            core=object(),
            memory=memory,
        )
    )

    assert result["ok"] is True
    assert result["text"] == "Vou preparar essa imagem."
    assert result["media"][0]["url"] == "/api/media/image/cat.png"
    assert "<gerar_imagem>" not in memory.recent_events(limit=1)[0]["content"]


def test_openrouter_image_provider_reasoning_self_healing(monkeypatch, tmp_path: Path) -> None:
    from hana_agent_oss.modules.vision.openrouter_image import OpenRouterImageProvider
    import urllib.request
    import urllib.error
    import json
    from io import BytesIO

    calls = []

    def _mock_urlopen(request, timeout=None):
        calls.append(request)
        if len(calls) == 1:
            fp = BytesIO(b'{"error":{"message":"The reasoning parameter is not supported by this model.","code":400}}')
            raise urllib.error.HTTPError(
                request.full_url, 400, "Bad Request", {"content-type": "application/json"}, fp
            )
        else:
            payload = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "images": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": "data:image/png;base64,ZmFrZQ=="
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
            resp = SimpleNamespace(
                read=lambda: json.dumps(payload).encode("utf-8"),
                status=200,
                fp=None
            )
            class MockResponse:
                def __enter__(self):
                    return resp
                def __exit__(self, exc_type, exc_val, exc_tb):
                    pass
            return MockResponse()

    monkeypatch.setattr(urllib.request, "urlopen", _mock_urlopen)
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake_key")

    provider = OpenRouterImageProvider(output_dir=str(tmp_path), model="test-model", reasoning="medium")
    result = provider.generate("A test prompt")

    assert result.ok is True
    assert len(calls) == 2
    assert result.filepath is not None
    assert Path(result.filepath).read_bytes() == b"fake"

