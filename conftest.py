from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
ROOT_STR = str(ROOT)
AGENT_ROOT_STR = str(ROOT / "!Hana_Agent_OSS")

if ROOT_STR not in sys.path:
    sys.path.insert(0, ROOT_STR)
if AGENT_ROOT_STR not in sys.path:
    sys.path.insert(1, AGENT_ROOT_STR)
