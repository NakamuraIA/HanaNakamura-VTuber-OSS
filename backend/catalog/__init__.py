"""Camada de catálogo de modelos LLM/TTS/STT servido pelo banco principal.

Estado atual:
- repository.py / tts_repository.py / stt_repository.py leem e escrevem as
  tabelas llm_models/tts_models/stt_models.
- llm/execution_policy.py : decide estratégia de execução por modelo.

Contrato: backend/bd/ cria e migra tabelas; catalog/ acessa dados; e
backend/providers/ conversa com APIs externas.
"""

from backend.catalog.repository import LlmModelRepository

__all__ = ["LlmModelRepository"]
