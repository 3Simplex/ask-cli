from pathlib import Path

# --- Paths & Global Config ---
CONF_DIR = Path("~/.config/ask").expanduser()
DATA_DIR = Path("~/.local/share/ask").expanduser()
THREAD_DIR = DATA_DIR / "threads"
ROUTINE_DIR = DATA_DIR / "routines"
PREF_FILE = CONF_DIR / "preferences.json"

API_BASE = "http://localhost:8080/v1"
API_URL = f"{API_BASE}/chat/completions"
API_MODELS_URL = f"{API_BASE}/models"
API_KEY = "KEY"

TIMEOUT = 240
MAX_RESULT_CHARS = 131768

# These will be set by CLI arguments
AUTO_APPROVE = False
USE_SANDBOX = False

WATCHER_LOG_DIR = DATA_DIR / "security_audit"

def init_dirs():
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    THREAD_DIR.mkdir(parents=True, exist_ok=True)
    ROUTINE_DIR.mkdir(parents=True, exist_ok=True)
    WATCHER_LOG_DIR.mkdir(parents=True, exist_ok=True)
