"""Travas da organização da memória concluída na fase 9."""

from pathlib import Path

from backend.memory.core import HanaMemory
from backend.memory.events import EventMemory
from backend.memory.fixed import FixedMemory
from backend.memory.long_term import LongTermMaintenance, LongTermSearch, LongTermStore
from backend.memory.short_term import ShortTermMemory
from backend.memory.store import MemoryStore


def test_tipos_de_memoria_ficam_em_pacotes_irmaos() -> None:
    root = Path("backend/memory")
    for package in ("short_term", "long_term", "fixed", "events"):
        assert (root / package / "__init__.py").is_file()


def test_fachadas_publicas_compõem_os_dominios_corretos() -> None:
    assert issubclass(HanaMemory, ShortTermMemory)
    assert issubclass(HanaMemory, FixedMemory)
    assert issubclass(MemoryStore, EventMemory)
    assert issubclass(MemoryStore, LongTermStore)
    assert issubclass(MemoryStore, LongTermSearch)
    assert issubclass(MemoryStore, LongTermMaintenance)


def test_caminhos_legados_internos_foram_removidos() -> None:
    root = Path("backend/memory")
    assert not (root / "semantic.py").exists()
    assert not (root / "extractor.py").exists()
    assert not (root / "sleep.py").exists()
