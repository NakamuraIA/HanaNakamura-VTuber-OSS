from __future__ import annotations

import json
from pathlib import Path


def test_qwen36_35b_tem_limites_oficiais_no_catalogo_publico() -> None:
    catalog_path = Path(__file__).resolve().parents[1] / "setup" / "defaults" / "llm_models.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    model = next(item for item in catalog["models"] if item["model_id"] == "qwen3.6-35b-a3b")

    assert model["max_input_tokens"] == 260096
    assert model["max_output_tokens"] == 65536
    assert model["supports_video"] is True
    assert model["supports_structured_output"] is True
