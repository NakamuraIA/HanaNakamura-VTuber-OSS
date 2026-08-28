"""Testes da compatibilidade temporária durante a migração dos providers."""

from backend.providers.provider_selector.selector import ProviderSelector


class _LegacyQwenCatalog:
    """Catálogo mínimo sem os campos novos da migração."""

    @staticmethod
    def get_model(provider: str, model_id: str) -> dict[str, object]:
        return {"id": model_id, "provider": provider, "supportsTools": True}


def test_legacy_catalog_receives_transitional_streaming_capabilities() -> None:
    """Mantém o streaming antigo sem recolocar a regra no chat."""
    selector = ProviderSelector()
    selector.get_provider("qwen").model_repository = _LegacyQwenCatalog()
    info = selector.get_model_info("qwen", "qwen-plus")

    assert info is not None
    assert info["supportsStreaming"] is True
    assert info["supportsStreamingTools"] is True
    assert info["_legacyCapabilityFallback"] is True
