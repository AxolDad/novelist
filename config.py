"""
config.py — Constants and Configuration

Central configuration for the novelist system.
All paths, timeouts, model names, and directory constants live here.
Settings are loaded from .env file with sensible defaults.
"""

import os
from prompt_loader import load_prompt
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ------------------------------------------------------------------
#  ENVIRONMENT
# ------------------------------------------------------------------
# FORCE DIRECT MODE (Fixes WSL Daemon locking issues)
os.environ["BD_DIRECT"] = "1"

# ------------------------------------------------------------------
#  LLM PROVIDER CONFIGURATION
# ------------------------------------------------------------------
# Provider: "ollama" for local, "openai" for OpenAI-compatible APIs
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()

# Model names (Split Brain Architecture)
WRITER_MODEL = os.getenv("WRITER_MODEL", "huihui_ai/deepseek-r1-abliterated:32b").strip()
CRITIC_MODEL = os.getenv("CRITIC_MODEL", "hf.co/DavidAU/L3.2-Rogue-Creative-Instruct-Uncensored-Abliterated-7B-GGUF:Q8_0").strip()

# ------------------------------------------------------------------
#  STORY ARCHITECTURE & CONTEXT
# ------------------------------------------------------------------
DEFAULT_TARGET_WORD_COUNT = int(os.getenv("DEFAULT_TARGET_WORD_COUNT", "15000"))
SCENE_WORD_TARGET_DEFAULT = int(os.getenv("SCENE_WORD_TARGET_DEFAULT", "1200"))
MANUSCRIPT_EXCERPT_CHARS = int(os.getenv("MANUSCRIPT_EXCERPT_CHARS", "6000"))
CHAPTER_HISTORY_LIMIT = int(os.getenv("CHAPTER_HISTORY_LIMIT", "5"))
CHAPTER_SIZE = int(os.getenv("CHAPTER_SIZE", "5")) # Scenes per chapter checkpoint
STATE_EXCERPT_CHARS = int(os.getenv("STATE_EXCERPT_CHARS", "4000"))
RECENT_PROSE_EXCERPT_CHARS = 1500
PROSE_CONTEXT_SCENES = 3
PROSE_CONTEXT_MAX_CHARS_EACH = 2000

# ------------------------------------------------------------------
#  TIMING & PACING
# ------------------------------------------------------------------
LOCAL_BREATH_SECONDS = 0.5


# ------------------------------------------------------------------
#  OLLAMA CONFIGURATION (Local)
# ------------------------------------------------------------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip('/')
OLLAMA_URL = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_TAGS_URL = f"{OLLAMA_BASE_URL}/api/tags"

# ------------------------------------------------------------------
#  OPENAI-COMPATIBLE API CONFIGURATION (Commercial)
# ------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ------------------------------------------------------------------
#  HUMAN-IN-THE-LOOP & AUTO-REVIEW
# ------------------------------------------------------------------
HUMAN_REVIEW_TIMEOUT = int(os.getenv("HUMAN_REVIEW_TIMEOUT", "300")) # 5 minutes default
AUTO_REVIEW_PROVIDER = os.getenv("AUTO_REVIEW_PROVIDER", "").lower() or LLM_PROVIDER
AUTO_REVIEW_MODEL = os.getenv("AUTO_REVIEW_MODEL", "").strip() or CRITIC_MODEL
AUTO_REVIEW_PROMPT = os.getenv("AUTO_REVIEW_PROMPT", load_prompt("critics", "auto_review.md"))

# ------------------------------------------------------------------
#  QUALITY & LINTING THRESHOLDS
# ------------------------------------------------------------------
LINT_REPETITION_THRESHOLD = 10
LINT_RHYTHM_THRESHOLD = 10
MIN_PROSE_PARA_LENGTH = 50
MAX_DRIFT_MARKERS = 18    # Max behavioral markers to keep in bible
MAX_DRIFT_VOICE_NOTES = 12 # Max voice notes to keep in bible
TRIBUNAL_PASS_SCORE = 90
LOG_TRUNCATE_CHARS = 100
LOG_TRUNCATE_CHARS_SMALL = 50

# Sanitization and output context
MAX_CONTEXT_WINDOW_DRAFT = 2400
MAX_REVIEW_EXCERPT_LEN = 1800

# ------------------------------------------------------------------
#  UI & UX SETTINGS
# ------------------------------------------------------------------
UI_BANNER_WIDTH = 60
UI_SECTION_WIDTH = 60
UI_PROGRESS_BAR_WIDTH = 30

# ------------------------------------------------------------------
#  FILE PATHS
# ------------------------------------------------------------------
MANIFEST_FILE = "story_manifest.json"
STATE_FILE = "world_state.json"
ARC_FILE = "arc_ledger.json"
CHAR_BIBLE_FILE = "character_bible.json"
STYLES_MASTER_FILE = "styles_master.json"
DB_FILE = "story.db"

# Meta directory files
META_DIR = "meta"
MACRO_OUTLINE_FILE = os.path.join(META_DIR, "macro_outline.json")
PROGRESS_FILE = os.path.join(META_DIR, "progress_ledger.json")

# ------------------------------------------------------------------
#  OUTPUT ORGANIZATION
# ------------------------------------------------------------------
OUTPUT_DIR = "outputs"
SCENES_DIR = "scenes"  # Primary scene output directory
MANUSCRIPT_FILE_DEFAULT = os.path.join(OUTPUT_DIR, "manuscript.md")

# ------------------------------------------------------------------
#  PROJECT DIRECTORIES
# ------------------------------------------------------------------
PLANNING_DIR = "planning"
EXPORTS_DIR = "exports"
LOGS_DIR = "logs"
SNAPSHOTS_DIR = os.path.join(META_DIR, "snapshots")
CHECKPOINT_DIR = os.path.join(META_DIR, "checkpoints")
LEGACY_CHECKPOINT_DIR = "checkpoints"

# ------------------------------------------------------------------
#  TIMEOUT & RETRY CONTROLS
# ------------------------------------------------------------------
# If you see: Read timed out. (read timeout=180) -> increase OLLAMA_READ_TIMEOUT
OLLAMA_CONNECT_TIMEOUT = int(os.getenv("OLLAMA_CONNECT_TIMEOUT", "250"))
OLLAMA_READ_TIMEOUT = int(os.getenv("OLLAMA_READ_TIMEOUT", "800"))
OLLAMA_MAX_RETRIES = int(os.getenv("OLLAMA_MAX_RETRIES", "5"))
OLLAMA_RETRY_BACKOFF_BASE = 3.0       # exponential backoff base
OLLAMA_RETRY_JITTER = 1.35            # jitter seconds added to backoff
OLLAMA_HTTP_TIMEOUT = (OLLAMA_CONNECT_TIMEOUT, OLLAMA_READ_TIMEOUT)
OLLAMA_CHECK_TIMEOUT = (5, 10)

# ------------------------------------------------------------------
#  LLM GENERIC SETTINGS & DEFAULTS
# ------------------------------------------------------------------
DEFAULT_NUM_CTX = int(os.getenv("DEFAULT_NUM_CTX", "32768"))
CONTEXT_RESERVE_TOKENS = 2000
CONTEXT_MIN_BUDGET_TOKENS = 1000
TOKEN_EST_CHARS_PER_TOKEN = 3.5
WRITER_TEMP_DEFAULT = 0.85
CRITIC_TEMP_DEFAULT = 0.3
CONTEXT_SLASH_RATIO = 0.7  # Slash 30% of content when over context


# ------------------------------------------------------------------
#  MODEL PERSONALITY PRESETS (Director's Dashboard - Protocol 4090)
# ------------------------------------------------------------------

# The Architect's Mandate (DeepSeek R1) - Forces deep reasoning
# The Architect's Mandate (DeepSeek R1) - Forces deep reasoning
ARCHITECT_SYSTEM_PROMPT = load_prompt("system", "architect.md")

# The Rogue's Canvas (L3.2 Rogue) - Brainstorm 40x activation
ROGUE_SYSTEM_PROMPT = load_prompt("system", "rogue.md")

MODEL_PRESETS = {
    "architect": {
        "name": "The Architect (DeepSeek R1)",
        "model": "huihui_ai/deepseek-r1-abliterated:32b",
        "description": "Logic-focused reasoning with Red Teaming",
        "parameters": {
            "temperature": 0.6,
            "top_p": 0.95,
            "repetition_penalty": 1.05,
            "max_tokens": 8192,
        },
        "system_prompt": ARCHITECT_SYSTEM_PROMPT,
    },
    "artist": {
        "name": "The Artist (L3.2 Rogue)",
        "model": "hf.co/DavidAU/L3.2-Rogue-Creative-Instruct-Uncensored-Abliterated-7B-GGUF:Q8_0",
        "description": "Brainstorm 40x: Sensory saturation & micro-focus",
        "parameters": {
            "temperature": 0.8,
            "repetition_penalty": 1.12,
            "smoothing_factor": 1.8,
            "min_p": 0.05,
            "max_tokens": 4096,
        },
        "system_prompt": ROGUE_SYSTEM_PROMPT,
        "masterstory_enabled": True,
    }
}
