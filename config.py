import os
from dotenv import load_dotenv

load_dotenv()

# Paths
CAPABILITY_LIBRARY_PATH = "./capability_library/"
CHROMA_DB_PATH = "./chroma_db/"
OUTPUT_PATH = "./output/"

# Model
MODEL_NAME = "claude-sonnet-4-5"

# Chunking
MAX_TOKENS_PER_CHUNK = 500
CHUNK_OVERLAP_TOKENS = 50

# Retrieval
MAX_RETRIEVAL_RESULTS = 50
MAX_GENERATION_CHUNKS = 35

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
