"""Fonte unica de verdade dos caminhos do projeto.

Todo caminho sai DAQUI, derivado da posicao deste arquivo. Mudar o layout do
projeto exige mexer so neste modulo, em vez de espalhar
``Path(__file__).resolve().parents[N]`` por dezenas de arquivos.

Layout::

    local-hana-oss/               -> PROJECT_ROOT
      backend/                    -> PACKAGE_DIR (este pacote)
        paths.py                  (este arquivo)
        skills/                   -> SKILLS_DIR
      data/                       scripts e imagens
      runtime/                    -> RUNTIME_DIR (memoria; fora do git)
      frontend/

Existe UM runtime so. O layout antigo tinha dois (um do projeto, um do agente)
e era a maior fonte de confusao: ninguem sabia qual banco estava sendo lido.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Ancoras (calculadas uma vez) ---------------------------------------- #
PACKAGE_DIR = Path(__file__).resolve().parent          # .../local-hana-oss/backend
PROJECT_ROOT = PACKAGE_DIR.parent                      # .../local-hana-oss

# --- Runtime (tudo que a Hana escreve; unica pasta com escrita) ---------- #
RUNTIME_DIR = PROJECT_ROOT / "runtime"

# --- Skills (manuais .md que a Hana le e escreve) ------------------------ #
SKILLS_DIR = PACKAGE_DIR / "skills"

# --- Scripts (codigo executavel que a Hana escreve pra si) --------------- #
# Skills sao documentos Markdown; scripts sao o codigo que eles apontam.
SCRIPTS_DIR = PROJECT_ROOT / "data" / "scripts"

# --- Memoria persistente ------------------------------------------------- #
MEMORY_DB = Path(os.environ.get("HANA_MEMORY_DB") or RUNTIME_DIR / "hana_memory.sqlite3").resolve()
MEMORY_EVENTS = Path(os.environ.get("HANA_MEMORY_EVENTS") or RUNTIME_DIR / "hana_events.jsonl").resolve()

# --- Midia gerada (imagens, audio) --------------------------------------- #
# Pasta propria: sao arquivos grandes e descartaveis, nao se misturam com banco.
MEDIA_DIR = RUNTIME_DIR / "media"

# --- Modelos locais (offline, leves) ------------------------------------- #
MODELS_DIR = PROJECT_ROOT / "models"                   # modelos onnx em cache local
SILERO_VAD_MODEL = MODELS_DIR / "silero_vad.onnx"      # VAD neural (Silero v5, ~2MB)

# --- Compatibilidade do runtime do agente + config MCP ------------------- #
# O Agent Core agora usa o banco principal. O nome antigo continua como alias
# de compatibilidade para nenhum import antigo voltar a criar um segundo banco.
RUNTIME_DB = MEMORY_DB
MCP_EXAMPLE_CONFIG = PACKAGE_DIR / "config" / "mcp_servers.example.json"
MCP_LOCAL_CONFIG = RUNTIME_DIR / "mcp_servers.local.json"

# Compatibilidade: nomes antigos que ainda aparecem em alguns modulos.
PROJECT_RUNTIME_DIR = RUNTIME_DIR
AGENT_RUNTIME_DIR = RUNTIME_DIR
AGENT_ROOT = PROJECT_ROOT
