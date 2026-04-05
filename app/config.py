import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = os.environ.get("PLAYGROUND_DB", str(DATA_DIR / "playground.db"))
HOST = os.environ.get("PLAYGROUND_HOST", "0.0.0.0")
PORT = int(os.environ.get("PLAYGROUND_PORT", "8000"))
TOKEN_BYTES = 32
SPECTATOR_QUEUE_MAX = 256

# Public URL at which this playground instance is reachable. Used in
# A2A Agent Cards so discovering agents know where to send requests.
PUBLIC_URL = os.environ.get("PLAYGROUND_PUBLIC_URL", f"http://localhost:{PORT}")
PLATFORM_NAME = os.environ.get("PLAYGROUND_NAME", "AI Playground")
PLATFORM_VERSION = "0.2.0"
