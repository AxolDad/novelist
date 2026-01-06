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
from logger import logger

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
    micro_outline TEXT, -- JSON dict (The plan)
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
    
    # Ensure update global active path if explicit path provided
    if path:
        set_db_path(path)
        
    # Ensure directory exists
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    
    
    with sqlite3.connect(target_path) as conn:
        conn.executescript(SCHEMA_SQL)
        
        # Schema Migration: Add micro_outline if missing
        try:
            conn.execute("ALTER TABLE scenes ADD COLUMN micro_outline TEXT")
            logger.info("Migrated schema: Added micro_outline to scenes table.")
        except sqlite3.OperationalError:
            pass # Column likely exists
            
        conn.commit()
    logger.info(f"Database initialized at {target_path}")

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
            # FIX: Unpack voice_notes if it's actually our JSON blob
            # This fixes the "Lobotomized" character loop
            profile_blob = {}
            voice_notes_str = r["voice_notes"]
            
            if voice_notes_str and voice_notes_str.strip().startswith("{"):
                try:
                    profile_blob = json.loads(voice_notes_str)
                    # If successful, use its internal voice_notes as the string text
                    # and unpack other fields to top level
                    voice_notes_str = profile_blob.get("voice_notes", "")
                    if isinstance(voice_notes_str, list):
                        voice_notes_str = "\n".join(voice_notes_str)
                except json.JSONDecodeError:
                    pass

            chars[r["name"]] = {
                "role": r["role"],
                "description": r["description"],
                "voice_notes": voice_notes_str, 
                "behavioral_markers": profile_blob.get("behavioral_markers", []),
                "hard_limits": profile_blob.get("hard_limits", []),
                "relationships": json.loads(r["relationships"] or "{}"),
                "current_status": json.loads(r["current_status"] or "{}")
            }
        return chars

# ------------------------------------------------------------------
#  SCENES
# ------------------------------------------------------------------
def log_scene(title: str, filename: str, content: str, meta: Dict[str, Any], micro_outline: Optional[Dict[str, Any]] = None):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO scenes (title, filename, content, summary, consequence, characters_present, word_count, tribunal_scores, micro_outline)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                filename,
                content,
                meta.get("summary", ""),
                meta.get("consequence", ""),
                json.dumps(meta.get("characters_present", [])),
                meta.get("word_count", 0),
                json.dumps(meta.get("tribunal_scores", {})),
                json.dumps(micro_outline) if micro_outline else None
            )
        )
        conn.commit()

def get_full_state_dump() -> Dict[str, Any]:
    """Get complete DB state efficiently (for Dashboard)."""
    with get_db() as conn:
        # KV
        kv = {}
        try:
            rows = conn.execute("SELECT key, value FROM kv_store").fetchall()
            for r in rows: kv[r["key"]] = json.loads(r["value"])
        except: pass
        
        # Chars
        chars = {}
        try:
            rows = conn.execute("SELECT * FROM characters").fetchall()
            for r in rows:
                profile = {}
                if r["voice_notes"] and r["voice_notes"].startswith("{"):
                    try: profile = json.loads(r["voice_notes"])
                    except: pass
                    
                chars[r["name"]] = {
                    "role": r["role"],
                    "description": r["description"],
                    "voice_notes": profile.get("voice_notes", []) if profile else r["voice_notes"], # Handle legacy
                    "behavioral_markers": profile.get("behavioral_markers", []),
                    "hard_limits": profile.get("hard_limits", []),
                    "relationships": json.loads(r["relationships"] or "{}"),
                    "current_status": json.loads(r["current_status"] or "{}")
                }
        except: pass

        # Arc
        arc = {"stakes": [], "promises_to_reader": [], "unresolved_questions": [], "scene_history": []}
        try:
            rows = conn.execute("SELECT type, description FROM arc_items WHERE status='active'").fetchall()
            for r in rows:
                if r["type"] == "stake": arc["stakes"].append(r["description"])
                elif r["type"] == "promise": arc["promises_to_reader"].append(r["description"])
                elif r["type"] == "question": arc["unresolved_questions"].append(r["description"])
                
            rows = conn.execute("SELECT * FROM scenes ORDER BY id DESC LIMIT 5").fetchall()
            for r in rows:
                arc["scene_history"].append({
                    "title": r["title"],
                    "summary": r["summary"],
                    "consequence": r["consequence"],
                    "scores": json.loads(r["tribunal_scores"] or "{}")
                })
            arc["scene_history"].reverse()
        except: pass
        
        
        return {"kv": kv, "chars": chars, "arc": arc}

def get_recent_scene_text(limit: int = 2) -> List[str]:
    """Get raw prose from recent scenes for context injection."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT title, content FROM scenes ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        
        # Return in chronological order (oldest -> newest)
        blocks = []
        for r in reversed(rows):
            blocks.append(f"\n--- {r['title']} (from DB) ---\n{r['content'][-3500:]}\n") # simple tail
        return blocks


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
    
    logger.info(f"Exported state to {base_path}")

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
    
    logger.info(f"Imported state from {base_path}")


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

