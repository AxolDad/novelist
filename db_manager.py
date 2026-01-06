"""
db_manager.py — SQLite Database Layer

Manages the 'story.db' SQLite database, replacing JSON file storage.
Handles:
- Schema initialization
- KV Store (World State)
- Character Profiles
- Scene History
- Arc Items (Stakes, Promises, Questions)
"""

import sqlite3
import json
import os
from contextlib import contextmanager
from typing import Dict, Any, List, Optional
from config import DB_FILE as DEFAULT_DB_FILE

# Global active DB path (can be changed by set_db_path)
_ACTIVE_DB_PATH = DEFAULT_DB_FILE

def set_db_path(path: str):
    """Set the active database file path."""
    global _ACTIVE_DB_PATH
    _ACTIVE_DB_PATH = path

# ------------------------------------------------------------------
#  SCHEMA
# ------------------------------------------------------------------
SCHEMA_SQL = """
-- Global Key-Value Store (Replaces world_state.json)
CREATE TABLE IF NOT EXISTS kv_store (
    key TEXT PRIMARY KEY,
    value TEXT, -- JSON value
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Character Profiles (Replaces character_bible.json)
CREATE TABLE IF NOT EXISTS characters (
    name TEXT PRIMARY KEY,
    role TEXT,
    description TEXT,
    voice_notes TEXT,
    relationships TEXT, -- JSON dict
    current_status TEXT, -- JSON dict (location, health)
    last_seen_scene_id INTEGER
);

-- Scene History (Replaces arc_ledger.json "scene_history")
CREATE TABLE IF NOT EXISTS scenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    filename TEXT UNIQUE,
    content TEXT, -- Full prose or path
    summary TEXT,
    consequence TEXT,
    characters_present TEXT, -- JSON list
    word_count INTEGER,
    tribunal_scores TEXT, -- JSON dict
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Arc Tracking (Replaces arc_ledger.json lists)
CREATE TABLE IF NOT EXISTS arc_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT, -- 'stake', 'promise', 'question', 'theme'
    description TEXT,
    status TEXT DEFAULT 'active', -- 'active', 'resolved', 'failed'
    resolution_scene_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ensure singleton row for global arc theme if not exists
INSERT OR IGNORE INTO kv_store (key, value) VALUES ('arc_theme', '"Unspecified"');
"""

# ------------------------------------------------------------------
#  DATABASE CONNECTION
# ------------------------------------------------------------------
@contextmanager
def get_db():
    conn = sqlite3.connect(_ACTIVE_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db(path: Optional[str] = None):
    """Initialize the database schema."""
    target_path = path or _ACTIVE_DB_PATH
    # Ensure directory exists
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    
    with sqlite3.connect(target_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    print(f"   💾 Database initialized at {target_path}")

# ------------------------------------------------------------------
#  KEY-VALUE STORE (World State)
# ------------------------------------------------------------------
def get_kv(key: str, default: Any = None) -> Any:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
        if row:
            return json.loads(row["value"])
    return default

def set_kv(key: str, value: Any):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO kv_store (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP",
            (key, json.dumps(value), json.dumps(value))
        )
        conn.commit()

# ------------------------------------------------------------------
#  ARC ITEMS
# ------------------------------------------------------------------
def add_arc_item(item_type: str, description: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO arc_items (type, description) VALUES (?, ?)",
            (item_type, description)
        )
        conn.commit()

def get_active_arc_items(item_type: str) -> List[str]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT description FROM arc_items WHERE type = ? AND status = 'active'",
            (item_type,)
        ).fetchall()
        return [r["description"] for r in rows]

# ------------------------------------------------------------------
#  CHARACTERS
# ------------------------------------------------------------------
def upsert_character(name: str, profile: Dict[str, Any]):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO characters (name, role, description, voice_notes, relationships, current_status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                role = excluded.role,
                description = excluded.description,
                voice_notes = excluded.voice_notes,
                relationships = excluded.relationships,
                current_status = excluded.current_status
            """,
            (
                name,
                profile.get("role", ""),
                profile.get("description", ""),
                profile.get("voice_notes", ""),
                json.dumps(profile.get("relationships", {})),
                json.dumps(profile.get("current_status", {}))
            )
        )
        conn.commit()

def get_all_characters() -> Dict[str, Any]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM characters").fetchall()
        chars = {}
        for r in rows:
            chars[r["name"]] = {
                "role": r["role"],
                "description": r["description"],
                "voice_notes": r["voice_notes"],
                "relationships": json.loads(r["relationships"] or "{}"),
                "current_status": json.loads(r["current_status"] or "{}")
            }
        return chars

# ------------------------------------------------------------------
#  SCENES
# ------------------------------------------------------------------
def log_scene(title: str, filename: str, content: str, meta: Dict[str, Any]):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO scenes (title, filename, content, summary, consequence, characters_present, word_count, tribunal_scores)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                filename,
                content,
                meta.get("summary", ""),
                meta.get("consequence", ""),
                json.dumps(meta.get("characters_present", [])),
                meta.get("word_count", 0),
                json.dumps(meta.get("tribunal_scores", {}))
            )
        )
        conn.commit()

def get_recent_scene_history(limit: int = 5) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM scenes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        # Return in chronological order (oldest to newest)
        history = []
        for r in rows:
            history.append({
                "title": r["title"],
                "summary": r["summary"],
                "consequence": r["consequence"],
                "characters": json.loads(r["characters_present"] or "[]"),
                "scores": json.loads(r["tribunal_scores"] or "{}")
            })
        return history[::-1]


# ------------------------------------------------------------------
#  HIGH-LEVEL STATE ACCESSORS (Single Source of Truth)
# ------------------------------------------------------------------

def get_world_state() -> Dict[str, Any]:
    """Get the complete world state from DB."""
    return get_kv("world_state", {})

def set_world_state(state: Dict[str, Any]):
    """Set the complete world state in DB."""
    set_kv("world_state", state)

def get_arc_ledger() -> Dict[str, Any]:
    """Get arc ledger from DB."""
    ledger = get_kv("arc_ledger", {})
    # Ensure proper structure
    if not isinstance(ledger, dict):
        ledger = {}
    ledger.setdefault("scene_history", [])
    ledger.setdefault("active_stakes", [])
    ledger.setdefault("narrative_promises", [])
    ledger.setdefault("open_questions", [])
    ledger.setdefault("tension_threads", {})
    return ledger

def set_arc_ledger(ledger: Dict[str, Any]):
    """Set arc ledger in DB."""
    set_kv("arc_ledger", ledger)

def get_progress() -> Dict[str, Any]:
    """Get progress ledger from DB."""
    return get_kv("progress", {"next_scene_index": 1})

def set_progress(progress: Dict[str, Any]):
    """Set progress ledger in DB."""
    set_kv("progress", progress)

def get_macro_outline() -> Dict[str, Any]:
    """Get macro outline from DB."""
    return get_kv("macro_outline", {})

def set_macro_outline(outline: Dict[str, Any]):
    """Set macro outline in DB."""
    set_kv("macro_outline", outline)

def get_character_bible() -> Dict[str, Any]:
    """Get character bible (wrapper for get_all_characters)."""
    return {"characters": get_all_characters()}

def set_character_bible(bible: Dict[str, Any]):
    """Set character bible (upserts all characters)."""
    chars = bible.get("characters", bible)  # Handle both formats
    for name, profile in chars.items():
        upsert_character(name, profile)


# ------------------------------------------------------------------
#  JSON EXPORT/IMPORT (For debugging and manual editing)
# ------------------------------------------------------------------

def export_state_to_json(base_path: str):
    """Export all DB state to JSON files for debugging."""
    import os
    
    # Create paths
    os.makedirs(base_path, exist_ok=True)
    
    exports = {
        "world_state.json": get_world_state(),
        "arc_ledger.json": get_arc_ledger(),
        "character_bible.json": get_character_bible(),
        os.path.join("meta", "progress_ledger.json"): get_progress(),
        os.path.join("meta", "macro_outline.json"): get_macro_outline(),
    }
    
    for filename, data in exports.items():
        filepath = os.path.join(base_path, filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    print(f"   📤 Exported state to {base_path}")

def import_state_from_json(base_path: str):
    """Import state from JSON files into DB (for startup sync)."""
    import os
    
    def load_if_exists(filepath):
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    
    # World state
    ws = load_if_exists(os.path.join(base_path, "world_state.json"))
    if ws:
        set_world_state(ws)
    
    # Arc ledger
    arc = load_if_exists(os.path.join(base_path, "arc_ledger.json"))
    if arc:
        set_arc_ledger(arc)
    
    # Character bible
    chars = load_if_exists(os.path.join(base_path, "character_bible.json"))
    if chars:
        set_character_bible(chars)
    
    # Progress
    prog = load_if_exists(os.path.join(base_path, "meta", "progress_ledger.json"))
    if prog:
        set_progress(prog)
    
    # Macro outline
    outline = load_if_exists(os.path.join(base_path, "meta", "macro_outline.json"))
    if outline:
        set_macro_outline(outline)
    
    print(f"   📥 Imported state from {base_path}")


def get_scene_count() -> int:
    """Get total number of scenes in DB."""
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM scenes").fetchone()
        return row["cnt"] if row else 0

def get_total_word_count() -> int:
    """Get total word count from all scenes in DB."""
    with get_db() as conn:
        row = conn.execute("SELECT SUM(word_count) as total FROM scenes").fetchone()
        return row["total"] or 0 if row else 0

