from pathlib import Path

# =============================================================================
# BASE DIRECTORIES & PROJECT STRUCTURE
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECTS_ROOT = BASE_DIR / "projects"  # Root folder where all project subfolders live

# These will be overridden dynamically in run.py via init_project()
# They represent the CURRENT active project's paths
CURRENT_PROJECT_PATH = None
CHARACTERS_DIR = None
SCRIPTS_DIR = None
PROMPTS_DIR = None
OUTPUT_DIR = None

# Static Workflow File Location (Not per-project, usually shared)
WORKFLOW_FILE = BASE_DIR / "workflows" / "ltx_msr_workflow.json"

# =============================================================================
# CHARACTER MAPPING (Default/Fallback)
# Note: In Project Mode, users upload specific images to CHARACTERS_DIR.
# This map is primarily for role naming conventions if auto-matching fails.
# =============================================================================
CHARACTER_MAP = {
    "hero": "hero.png",
    "villain": "villain.png",
    "heroin": "heroin.png",
    "sidekick": "sidekick.png",
}
DEFAULT_CHARACTER = "hero.png" 

# =============================================================================
# VIDEO GENERATION SETTINGS
# =============================================================================
# Duration Options (Seconds) - Supported by LTX-2.5 MSR
DURATION_OPTIONS = [5, 7, 10, 12, 15, 17, 20]
DEFAULT_DURATION = 10

# Alias for clarity in some modules
CLIP_DURATIONS = DURATION_OPTIONS 
DEFAULT_CLIP_DURATION = DEFAULT_DURATION

# Technical Constraints
MAX_WORDS_PER_DIALOGUE = 18  # Approx 1.8 words/sec allows natural pacing + pauses
TARGET_MEGAPIXELS = 0.5      # KEEP HIGH QUALITY (Do not reduce unless VRAM constrained)

# Aspect Ratios (Must match ComfyUI ResolutionSelector labels EXACTLY)
ASPECT_RATIOS = {
    "16:9": "16:9 (Widescreen)",
    "9:16": "9:16 (Portrait Widescreen)",
    "1:1": "1:1 (Square)",
    "4:3": "4:3 (Standard)",
    "21:9": "21:9 (Ultrawide)"
}
DEFAULT_ASPECT_RATIO = "16:9"

# =============================================================================
# API ENDPOINTS & MODELS
# =============================================================================
COMFYUI_URL = "http://127.0.0.1:8188"
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen3.8:27b"  # Vision-Capable Model

# =============================================================================
# COMFYUI WORKFLOW NODE IDS
# Must match ltx_msr_workflow.json exactly
# =============================================================================
WORKFLOW_NODE_IDS = {
    "IMAGE_INPUT_NODE_ID": "28",       # Primary Image Node (Hero)
    "GLOBAL_PROMPT_NODE_ID": "159",    # String Input for Global Refs
    "LOCAL_PROMPT_NODE_ID": "160",     # String Input for Scene Prompt
    "NEGATIVE_PROMPT_NODE_ID": "6",    # Negative Prompt Node
    "SEED_STAGE_1": "103_15",          # Seed Control Net/Stage 1
    "SEED_STAGE_2": "102_78",          # Seed Diffusion/Stage 2
    "DURATION_NODE_ID": "74",          # Integer Input for Seconds
}

# Define all possible Image Input Nodes (Max 2 based on your request)
# These correspond to "PIC 1" and "PIC 2" in ltx_msr_workflow.json
IMAGE_NODES = {
    1: "28",  # PIC 1 (Hero)
    2: "29"   # PIC 2 (Secondary Character / Villain / Heroine)
}

# =============================================================================
# LANGUAGE OPTIONS
# =============================================================================
LANGUAGES = {
    "en": "English",
    "ur-roman": "Romanized Urdu",
    "ps-roman": "Romanized Pashto",
    "ar": "Arabic",
    "fa": "Persian",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "ru": "Russian",
    "zh": "Chinese"
}
DEFAULT_LANGUAGE = "en"

# =============================================================================
# VISION MODEL CONFIGURATION
# =============================================================================
SUPPORTS_VISION = True 
VISION_PROMPT_TEMPLATE = """Describe this image in terms of a cinematic prompt for {role_name}.
Include:
- Physical appearance (age, hair, eyes, skin).
- Clothing and accessories (fabric, color, condition).
- Lighting and atmosphere.
- Pose and expression.
Output ONLY the descriptive text. No intro/outro."""

# =============================================================================
# PROMPT REVIEWER / QA AGENT SETTINGS
# =============================================================================
ENABLE_PROMPT_REVIEWER = True
MAX_RETRIES_PER_SCENE = 2  # Retry up to 2 times if prompt fails validation against LTX rules

# =============================================================================
# SCRAPER / TRENDING TOPICS (Optional External Keys)
# =============================================================================
# If using RapidAPI for trending topics, uncomment and fill these:
# RAPIDAPI_KEY = "YOUR_REAL_API_KEY_HERE"
# RAPIDAPI_HOST = "youtube-v31.p.rapidapi.com"
# REGION_CODE = "US"
# MAX_TRENDING_RESULTS = 10