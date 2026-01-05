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
