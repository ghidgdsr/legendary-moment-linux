import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

TOKEN_FILE = Path("/tmp/leica-test-token.txt")
TOKEN_FILE.write_text("test-token\n", encoding="utf-8")
try:
    TOKEN_FILE.chmod(0o600)
except OSError:
    pass
os.environ["LEICA_TOKEN_FILE"] = str(TOKEN_FILE)

os.environ.setdefault("LEICA_DATA_DIR", "/tmp/leica-test-jobs")
os.environ.setdefault("LEICA_MAX_QUEUE", "1")
