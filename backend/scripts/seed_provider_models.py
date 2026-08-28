"""Compatibilidade para a antiga carga manual de modelos.

Os registros não ficam mais neste arquivo. A fonte pública agora são os três
JSONs de ``backend/setup/defaults`` e toda escrita exige ``--confirm``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.setup.database import restore_defaults


def seed_all(db_path: str | Path = "", *, confirm: bool = False) -> int:
    """Mostra a prévia ou restaura os três catálogos quando confirmado."""

    result = restore_defaults("all", confirm=confirm, db_path=db_path or None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compatibilidade da carga pública de modelos.")
    parser.add_argument("db_path", nargs="?", default="")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    return seed_all(args.db_path, confirm=args.confirm)


if __name__ == "__main__":
    raise SystemExit(main())
