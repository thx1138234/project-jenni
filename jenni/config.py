"""jenni/config.py — Database paths, environment loading, constants."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Database paths
DB_IPEDS     = PROJECT_ROOT / "data" / "databases" / "ipeds_data.db"
DB_990       = PROJECT_ROOT / "data" / "databases" / "990_data.db"
DB_QUANT     = PROJECT_ROOT / "data" / "databases" / "institution_quant.db"
DB_EADA      = PROJECT_ROOT / "data" / "databases" / "eada_data.db"
DB_SCORECARD = PROJECT_ROOT / "data" / "databases" / "scorecard_data.db"
DB_DOCUMENTS = PROJECT_ROOT / "data" / "databases" / "jenni_documents.db"


def load_env() -> None:
    """Load .env file into os.environ without overriding existing env vars."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get_api_key() -> str:
    """Return ANTHROPIC_API_KEY from env. Raises ValueError if missing."""
    load_env()
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. "
            "Add it to .env (ANTHROPIC_API_KEY=sk-ant-...) or export it."
        )
    return key


# Model IDs — never log or print these alongside the API key
MODEL_HAIKU  = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_OPUS   = "claude-opus-4-6"

# Quant layer
FORMULA_VERSION = "1.0"
PRIMARY_YEAR    = 2022   # latest year with full financial data

# Accordion temporal bounds
BACKWARD_TERMINUS_IPEDS = 2000   # IPEDS structured data
BACKWARD_TERMINUS_990   = 2012   # 990 XML filings (ProPublica)
BACKWARD_TERMINUS_990_SUPPLEMENTAL = 2019  # TEOS supplemental schedules
FORWARD_TERMINUS_DEFENSIBLE = 2027  # 3–5 year projection horizon

# Peer group: min peers required for peer stats to be shown
MIN_PEER_COUNT = 5
