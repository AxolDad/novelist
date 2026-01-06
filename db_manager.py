"""
db_manager.py — Client-Side Database Layer (API Client)

Drop-in replacement for the old SQLite direct-access module.
Redirects all calls to the centralized `server.py` via HTTP.
Prevents "database locked" errors in multi-process use.
"""

import requests
import json
import os
from typing import Dict, Any, List, Optional
from config import DB_FILE # Unused directly, but good for back-compat imports
from logger import logger

API_BASE_URL = os.environ.get("NOVELIST_API_URL", "http://127.0.0.1:8000")

def _handle_response(resp):
    try:
        if resp.status_code == 200:
            return resp.json()
        logger.error(f"API Error {resp.status_code}: {resp.text}")
        return None
    except Exception as e:
        logger.error(f"API Request Failed: {e}")
        return None

# ------------------------------------------------------------------
#  INIT
# ------------------------------------------------------------------

def init_db(path: Optional[str] = None):
    """Tell server to initialize DB at path."""
    url = f"{API_BASE_URL}/meta/init"
    # We pass path if provided, otherwise server uses its default
    try:
        requests.post(url, json={"path": path}, timeout=10)
        logger.info(f"Requested DB Init at {path} via {API_BASE_URL}")
    except Exception as e:
        logger.error(f"Failed to init DB at server: {e}")

def set_db_path(path: str):
    # This is tricky in client-server mode. 
    # Usually we want to tell the server "Switch context to this DB".
    # But server is a singleton.
    # Ideally, we re-call init_db with the new path?
    # For now, let's assume we just re-init.
    init_db(path)

# ------------------------------------------------------------------
#  KEY-VALUE STORE
# ------------------------------------------------------------------

def get_kv(key: str, default: Any = None) -> Any:
    try:
        resp = requests.get(f"{API_BASE_URL}/kv/{key}", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            val = data.get("value")
            return val if val is not None else default
        return default
    except Exception:
        return default

def set_kv(key: str, value: Any):
    try:
        requests.post(f"{API_BASE_URL}/kv", json={"key": key, "value": value}, timeout=10)
    except Exception as e:
        logger.error(f"KV Set Failed: {e}")

# ------------------------------------------------------------------
#  ARC ITEMS
# ------------------------------------------------------------------

def add_arc_item(item_type: str, description: str):
    try:
        requests.post(f"{API_BASE_URL}/arc", json={"type": item_type, "description": description})
    except Exception as e:
        logger.error(f"Add Arc Item Failed: {e}")

def get_active_arc_items(item_type: str) -> List[str]:
    try:
        resp = requests.get(f"{API_BASE_URL}/arc/{item_type}", timeout=10)
        if resp.status_code == 200:
            return resp.json().get("items", [])
        return []
    except Exception:
        return []

# ------------------------------------------------------------------
#  CHARACTERS
# ------------------------------------------------------------------

def upsert_character(name: str, profile: Dict[str, Any]):
    try:
        requests.post(f"{API_BASE_URL}/characters/{name}", json={"name": name, "profile": profile}, timeout=10)
    except Exception as e:
        logger.error(f"Upsert Character Failed: {e}")

def get_all_characters() -> Dict[str, Any]:
    try:
        resp = requests.get(f"{API_BASE_URL}/characters", timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return {}
    except Exception:
        return {}

# ------------------------------------------------------------------
#  SCENES
# ------------------------------------------------------------------

def log_scene(title: str, filename: str, content: str, meta: Dict[str, Any], micro_outline: Optional[Dict[str, Any]] = None):
    try:
        requests.post(f"{API_BASE_URL}/scenes", json={
            "title": title,
            "filename": filename,
            "content": content,
            "meta": meta,
            "micro_outline": micro_outline
        }, timeout=10)
    except Exception as e:
        logger.error(f"Log Scene Failed: {e}")

def get_recent_scene_history(limit: int = 5) -> List[Dict[str, Any]]:
    try:
        resp = requests.get(f"{API_BASE_URL}/scenes/recent?limit={limit}", timeout=10)
        if resp.status_code == 200:
            return resp.json().get("history", [])
        return []
    except Exception:
        return []

def get_recent_scene_text(limit: int = 2) -> List[str]:
    try:
        resp = requests.get(f"{API_BASE_URL}/scenes/text?limit={limit}", timeout=10)
        if resp.status_code == 200:
            return resp.json().get("blocks", [])
        return []
    except Exception:
        return []

def get_scene_count() -> int:
    try:
        resp = requests.get(f"{API_BASE_URL}/scenes/count", timeout=10)
        if resp.status_code == 200:
            return resp.json().get("count", 0)
        return 0
    except Exception:
        return 0

def get_total_word_count() -> int:
    try:
        resp = requests.get(f"{API_BASE_URL}/scenes/words", timeout=10)
        if resp.status_code == 200:
            return resp.json().get("total", 0)
        return 0
    except Exception:
        return 0

def get_full_state_dump() -> Dict[str, Any]:
    try:
        resp = requests.get(f"{API_BASE_URL}/state/dump", timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return {}
    except Exception:
        return {}
    
# ------------------------------------------------------------------
#  HIGH-LEVEL ACCESSORS (Wrappers)
# ------------------------------------------------------------------
# These are kept for compatibility; they internally use the client functions above.

def get_world_state() -> Dict[str, Any]:
    return get_kv("world_state", {})

def set_world_state(state: Dict[str, Any]):
    set_kv("world_state", state)

def get_arc_ledger() -> Dict[str, Any]:
    ledger = get_kv("arc_ledger", {})
    if not isinstance(ledger, dict):
        ledger = {}
    ledger.setdefault("scene_history", [])
    return ledger

def set_arc_ledger(ledger: Dict[str, Any]):
    set_kv("arc_ledger", ledger)

def get_progress() -> Dict[str, Any]:
    return get_kv("progress", {"next_scene_index": 1})

def set_progress(progress: Dict[str, Any]):
    set_kv("progress", progress)

def get_macro_outline() -> Dict[str, Any]:
    return get_kv("macro_outline", {})

def set_macro_outline(outline: Dict[str, Any]):
    set_kv("macro_outline", outline)

# For compatibility
def get_db():
    raise NotImplementedError("Direct DB access removed. Use API.")
