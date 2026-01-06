import os
from functools import lru_cache

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")

@lru_cache(maxsize=None)
def load_prompt(category: str, filename: str) -> str:
    """
    Load a prompt from the prompts directory.
    Cached to avoid repeated file I/O.
    
    Args:
        category: Subdirectory name (e.g. 'critics', 'system', 'templates')
        filename: Filename with extension (e.g. 'prose.md')
    
    Returns:
        The content of the prompt file.
    """
    path = os.path.join(PROMPTS_DIR, category, filename)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        return f"ERROR: Prompt file not found: {path}"
    except Exception as e:
        return f"ERROR: Could not load prompt {path}: {e}"
