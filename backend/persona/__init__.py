"""Identidade da Hana: perfil e prompts de sistema.

Contrato da pasta:
- profile.py : perfil público e genérico da Hana; nomes vêm do ambiente.
- prompts.py : monta o system prompt, inclui regras específicas do provider,
  skills e as regras fixas privadas lidas da tabela pinned.

Regra: informação pessoal e o ajuste privado da personagem não entram no
profile.py público; ficam no banco local. A identidade pública continua aqui.
"""

from __future__ import annotations

from backend.persona.profile import PersonaProfile, default_persona_profile
from backend.persona.prompts import (
    build_provider_system_prompt,
    build_stt_prompt,
)

__all__ = [
    "PersonaProfile",
    "build_provider_system_prompt",
    "build_stt_prompt",
    "default_persona_profile",
]
