# =============================================================
#  config.py
#  Works automatically on Railway (reads environment variables).
#  For local use, fill in the fallback values below.
# =============================================================

import os

# ── PostgreSQL ──────────────────────────────────────────────────
# On Railway: these are set automatically — you change nothing.
# Local use : replace the "localhost" / "your_password" defaults.
DB = {
    "host":     os.environ.get("PGHOST",     "localhost"),
    "port":     int(os.environ.get("PGPORT", 5432)),
    "dbname":   os.environ.get("PGDATABASE", "materia_medica"),
    "user":     os.environ.get("PGUSER",     "postgres"),
    # No fake default: an empty password fails loudly instead of "your_password" failing mysteriously.
    "password": os.environ.get("PGPASSWORD", ""),
}

# ── HTTP behaviour ─────────────────────────────────────────────
REQUEST_DELAY_SECONDS = 1.5
REQUEST_TIMEOUT       = 25
MAX_RETRIES           = 3

# ── Quality gate thresholds ────────────────────────────────────
MIN_INTRODUCTION_CHARS = 80
MIN_SECTIONS_COUNT     = 3
MIN_SECTION_CHARS      = 20
MIN_TOTAL_CHARS        = 400

# ── Sources ────────────────────────────────────────────────────
# Each source can be switched with an environment variable (SCRAPE_KENT=0 etc.).
def _flag(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0") == "1"

SCRAPE_MATERIAMEDICA = _flag("SCRAPE_MATERIAMEDICA", True)    # Boericke, materiamedica.info
SCRAPE_KENT          = _flag("SCRAPE_KENT", True)             # Kent,     materiamedica.info
# homeoint.org (Boericke again, other site): the database holds no data from it and the path
# below is a different book than the Repertory. Off unless asked for.
SCRAPE_HOMEOINT      = _flag("SCRAPE_HOMEOINT", False)

MATERIAMEDICA_INDEX = (
    "https://www.materiamedica.info"
    "/en/materia-medica/william-boericke/index"
)
MATERIAMEDICA_BASE  = "https://www.materiamedica.info"
KENT_INDEX = (
    "https://www.materiamedica.info"
    "/en/materia-medica/james-tyler-kent/index"
)
KENT_MIN_TOTAL_CHARS = 1500   # Kent pages are long lectures without labelled sections

HOMEOINT_BASE    = "https://www.homeoint.org/books/boericmm/"
HOMEOINT_LETTERS = list("abcdefghijklmnopqrstuvwxyz")

# ── Logging ────────────────────────────────────────────────────
LOG_FILE = None   # Railway streams logs to dashboard — no file needed
