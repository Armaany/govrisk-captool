import os
from dotenv import load_dotenv

load_dotenv()

# Paths
CAPABILITY_LIBRARY_PATH = "./capability_library/"
CHROMA_DB_PATH = "./chroma_db/"
OUTPUT_PATH = "./output/"

# Models and paid-request limits
#
# Keep MODEL_NAME as the backwards-compatible drafting default.  Extraction is
# deliberately separated so a smaller model can do the structured ToR pass
# without paying Sonnet rates.  Every value can be changed in Streamlit secrets
# or the environment without a code deployment.
MODEL_NAME = os.getenv("MODEL_NAME", "claude-sonnet-4-5")
EXTRACTION_MODEL_NAME = os.getenv("EXTRACTION_MODEL_NAME", "claude-haiku-4-5")
GENERATION_MODEL_NAME = os.getenv("GENERATION_MODEL_NAME", MODEL_NAME)


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read a bounded positive integer without making config import fragile."""
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


ANTHROPIC_TIMEOUT_SECONDS = _bounded_int_env(
    "ANTHROPIC_TIMEOUT_SECONDS", 90, 10, 300
)
EXTRACTION_TIMEOUT_SECONDS = _bounded_int_env(
    "EXTRACTION_TIMEOUT_SECONDS", ANTHROPIC_TIMEOUT_SECONDS, 10, 300
)
GENERATION_TIMEOUT_SECONDS = _bounded_int_env(
    "GENERATION_TIMEOUT_SECONDS", 240, 30, 600
)
EXTRACTION_MAX_TOKENS = _bounded_int_env(
    "EXTRACTION_MAX_TOKENS", 3000, 512, 6000
)
GENERATION_MAX_TOKENS = _bounded_int_env(
    "GENERATION_MAX_TOKENS", 8000, 1000, 12000
)

# Chunking
MAX_TOKENS_PER_CHUNK = 500
CHUNK_OVERLAP_TOKENS = 50

# Retrieval
MAX_RETRIEVAL_RESULTS = 50
MAX_GENERATION_CHUNKS = _bounded_int_env(
    "MAX_GENERATION_CHUNKS", 20, 5, 35
)

# Filter options
GEOGRAPHY_OPTIONS = [
    "Mexico", "Colombia", "Peru", "Brazil",
    "Caribbean", "Central America", "Argentina",
    "Chile", "Regional / LATAM"
]

THEMATIC_OPTIONS = [
    "AML/CFT", "CTF/Terrorist Financing", "Anti-corruption",
    "FIU Strengthening", "Asset Recovery", "Justice Reform",
    "Beneficial Ownership", "DNFBP Supervision",
    "Illicit Financial Flows", "Human Trafficking"
]

FUNDER_OPTIONS = [
    "US State Dept", "UK FCDO", "IDB", "USAID", "IADB", "Other"
]

# API Key
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
