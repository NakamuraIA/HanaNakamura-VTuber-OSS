from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_configuracao_define_um_unico_caminho_de_banco(tmp_path: Path) -> None:
    database_path = (tmp_path / "hana-configurada.sqlite3").resolve()
    environment = dict(os.environ, HANA_MEMORY_DB=str(database_path))
    code = (
        "from backend.paths import MEMORY_DB; "
        "from backend.catalog.repository import LlmModelRepository; "
        "from backend.memory.store import MemoryStore; "
        "store = MemoryStore(); "
        "catalog = LlmModelRepository(); "
        "print(MEMORY_DB); print(store.db_path); print(catalog.db_path)"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip().splitlines() == [str(database_path)] * 3
