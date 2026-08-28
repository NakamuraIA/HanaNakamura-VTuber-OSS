from __future__ import annotations

from backend.api.routers.config import normalize_image_config
from backend.modules.vision.image_provider import (
    IMPLEMENTED_IMAGE_PROVIDERS,
    normalize_image_provider,
)
from backend.modules.vision.openrouter_image import OpenRouterImageProvider


def test_config_antiga_migra_para_image_model() -> None:
    config = normalize_image_config({"openrouterImageModel": "modelo-antigo"})
    assert config["imageModel"] == "modelo-antigo"
    assert config["openrouterImageModel"] == "modelo-antigo"


def test_image_model_novo_tem_prioridade() -> None:
    config = normalize_image_config({
        "imageModel": "modelo-novo",
        "openrouterImageModel": "modelo-antigo",
    })
    assert config["imageModel"] == "modelo-novo"
    assert config["openrouterImageModel"] == "modelo-novo"


def test_registro_expoe_somente_providers_implementados() -> None:
    assert IMPLEMENTED_IMAGE_PROVIDERS == ("gemini_api", "openrouter")
    assert normalize_image_provider("qwen") == "gemini_api"


def test_openrouter_le_campo_novo_e_legado(tmp_path) -> None:
    class Memory:
        def __init__(self, config):
            self.config = config

        def get_setting(self, key, default=None):
            return self.config if key == "image_config" else default

    novo = OpenRouterImageProvider(str(tmp_path / "novo"), memory=Memory({"imageModel": "modelo-novo"}))
    antigo = OpenRouterImageProvider(str(tmp_path / "antigo"), memory=Memory({"openrouterImageModel": "modelo-antigo"}))
    assert novo.default_model == "modelo-novo"
    assert antigo.default_model == "modelo-antigo"
