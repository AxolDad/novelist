"""
state_manager.py — State Management (DB-Backed)

Handles all story state by wrapping db_manager.py.
Replaces legacy JSON file operations with SQLite transactions.
"""

import json
import re
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import db_manager as db
from config import (
    MANIFEST_FILE,
    STATE_EXCERPT_CHARS,
    CRITIC_MODEL
)
from file_utils import (
    safe_read_json,
    tail_excerpt,
    list_completed_scene_files
)
from ollama_client import call_ollama, extract_clean_json


# ------------------------------------------------------------------
#  WORD COUNT
# ------------------------------------------------------------------
def get_target_word_count(manifest: Dict[str, Any]) -> int:
    """Get the target word count from manifest."""
    try:
        if isinstance(manifest.get("target_word_count"), int):
            return int(manifest["target_word_count"])
        style = manifest.get("style", {}) or {}
        if isinstance(style.get("target_word_count"), int):
            return int(style["target_word_count"])
    except Exception:
        pass
    return 90000


def compute_current_word_count(manifest: Optional[Dict[str, Any]] = None, manuscript_file_default: str = "") -> int:
    """Computes total word count from DB scenes."""
    # We ignore file scanning now and trust the DB, 
    # but we can fallback or sync if needed. For now, DB sum:
    try:
        with db.get_db() as conn:
            row = conn.execute("SELECT sum(word_count) as total FROM scenes").fetchone()
            if row and row["total"] is not None:
                return int(row["total"])
    except sqlite3.OperationalError:
        # Table might not exist yet if project is brand new or not initialized
        pass
            
    # Fallback to legacy file scan if DB empty (e.g. initial migration with no word counts)
    total = 0
    for fn in list_completed_scene_files():
        try:
            txt = open(fn, "r", encoding="utf-8").read()
            total += len(re.findall(r"\b\w+\b", txt))
        except Exception:
            pass
    return total


# ------------------------------------------------------------------
#  ARC LEDGER
# ------------------------------------------------------------------
def seed_arc_ledger(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Load arc ledger from DB."""
    return {
        "theme": db.get_kv("arc_theme", "Unspecified"),
        "stakes": db.get_active_arc_items("stake"),
        "promises_to_reader": db.get_active_arc_items("promise"),
        "unresolved_questions": db.get_active_arc_items("question"),
        "payoffs_delivered": [], # active items don't track delivered
        "scene_history": db.get_recent_scene_history(5)
    }


def ensure_arc_ledger_schema(arc_ledger: Any, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures structure (noop for DB, just reloads)."""
    return seed_arc_ledger(manifest)


def update_arc_ledger(
    arc_ledger: Dict[str, Any], 
    title: str, 
    micro_outline: Dict[str, Any], 
    scene_text: str,
    filename: str = "" # New optional arg
) -> Dict[str, Any]:
    """
    Update arc ledger based on new scene.
    Writes updates to DB.
    """
    # Truncate scene_history to last 5 entries for prompt efficiency
    arc_excerpt = arc_ledger.copy()
    if "scene_history" in arc_excerpt and len(arc_excerpt["scene_history"]) > 5:
        arc_excerpt["scene_history"] = arc_excerpt["scene_history"][-5:]
    
    prompt = f"""
Return JSON ONLY.

Update ARC LEDGER based on the new scene. Keep updates minimal and specific.
Do NOT invent giant plot turns unless clearly in the scene.

CURRENT ARC LEDGER (recent history only):
{json.dumps(arc_excerpt, indent=2)}

SCENE TITLE: {title}

MICRO-OUTLINE USED:
{json.dumps(micro_outline, indent=2)}

SCENE (tail excerpt):
{tail_excerpt(scene_text, STATE_EXCERPT_CHARS)}

OUTPUT JSON:
{{
  "stakes_add": [ ... ],
  "promises_add": [ ... ],
  "unresolved_add": [ ... ],
  "unresolved_resolved": [ ... ],
  "payoffs_add": [ ... ],
  "scene_history_add": {{
     "title": "...",
     "want": "...",
     "turn": "...",
     "consequence": "...",
     "new_pressure": "one line"
  }}
}}
"""
    out = call_ollama([{"role": "user", "content": prompt}], model=CRITIC_MODEL, json_mode=True)
    data = extract_clean_json(out)
    if not data:
        return arc_ledger

    # WRITE TO DB
    for s in data.get("stakes_add", []):
         if s: db.add_arc_item("stake", str(s))
    
    for p in data.get("promises_add", []):
         if p: db.add_arc_item("promise", str(p))
         
    for q in data.get("unresolved_add", []):
         if q: db.add_arc_item("question", str(q))
         
    # Resolving items is complex via string matching, 
    # for now we assume they are marked resolved in the prompt logic,
    # but the DB doesn't support 'resolving' via simple unique string yet
    # without IDs. We'll skip marking 'status=resolved' in DB for this iteration,
    # relying on the additive nature. 
    # Future improvement: Fetch ID map.

    # LOG SCENE
    sh = data.get("scene_history_add")
    if isinstance(sh, dict):
        summary = f"{sh.get('want','')} -> {sh.get('turn','')}"
        consequence = sh.get('consequence', '')
        
        # Word count
        wc = len(re.findall(r"\b\w+\b", scene_text))
        
        db.log_scene(
            title=title,
            filename=filename or f"scene_{int(wc)}.txt", # Fallback if no filename
            content=scene_text,
            meta={
                "summary": summary,
                "consequence": consequence,
                "characters_present": [], # Could extract from world state?
                "word_count": wc,
                "tribunal_scores": {} # We don't have them here easily, stored in 'draft' text?
            }
        )

    # Return refreshed object
    return seed_arc_ledger({})


# ------------------------------------------------------------------
#  CHARACTER BIBLE
# ------------------------------------------------------------------
def seed_character_bible(world_state: Dict[str, Any]) -> Dict[str, Any]:
    """Load character bible from DB."""
    return {"characters": db.get_all_characters()}


def update_character_bible(
    char_bible: Dict[str, Any], 
    scene_text: str, 
    world_state: Dict[str, Any]
) -> Dict[str, Any]:
    """Update character bible with observed behavioral markers. Writes to DB."""
    # Truncate
    bible_excerpt = {"characters": {}}
    for name, data in (char_bible.get("characters") or {}).items():
        bible_excerpt["characters"][name] = {
            "behavioral_markers": (data.get("behavioral_markers") or [])[-6:],
            "voice_notes": (data.get("voice_notes") or [])[-4:],
            "hard_limits": (data.get("hard_limits") or [])[-4:]
        }
    
    world_chars = {k: v for k, v in (world_state.get("characters") or {}).items()}
    
    prompt = f"""
Return JSON ONLY.

Update the character bible with *observed* behavioral markers from this scene.
Markers should be forensic-style cues (choices, tells, avoidance, tactics, sensory focus).
Do NOT use labels like "ADHD", "INFP", "narcissistic", etc.

CURRENT BIBLE (recent markers only):
{json.dumps(bible_excerpt, indent=2)}

WORLD STATE CHARACTERS:
{json.dumps(world_chars, indent=2)}

SCENE (excerpt):
{scene_text[:1800]}

OUTPUT JSON:
{{
  "updates": {{
     "<CharacterName>": {{
        "behavioral_markers_add": ["...", "..."],
        "voice_notes_add": ["..."],
        "hard_limits_add": ["..."]
     }}
  }}
}}
"""
    out = call_ollama([{"role": "user", "content": prompt}], model=CRITIC_MODEL, json_mode=True)
    data = extract_clean_json(out)
    if not data:
        return char_bible

    updates = data.get("updates", {})
    if not isinstance(updates, dict):
        return char_bible

    # WRITE TO DB
    # We need to fetch current char to append, or let upsert handle it?
    # Schema says 'roles', 'description', etc.
    # We are updating JSON fields inside 'voice_notes' text? 
    # Wait, 'voice_notes' in DB is text.
    # But here we treat it as list.
    # The DB manager expects 'voice_notes' as TEXT.
    # I should change DB manager to store JSON for these lists?
    # Or serialization.
    
    # Reload full bible to append correctly
    current_bible = db.get_all_characters()
    
    for name, upd in updates.items():
        if name not in current_bible:
            # Create new empty char if unknown
            current_bible[name] = {
                "role": "Unknown", "description": "", 
                "behavioral_markers": [], "voice_notes": [], "hard_limits": [], 
                "relationships": {}, "current_status": {}
            }
            
        c = current_bible[name]
        
        # Merge lists
        bm = (c.get("behavioral_markers") or []) + (upd.get("behavioral_markers_add") or [])
        vn = (c.get("voice_notes") or []) + (upd.get("voice_notes_add") or [])
        hl = (c.get("hard_limits") or []) + (upd.get("hard_limits_add") or [])
        
        # Dedupe
        def dd(lst): return list(dict.fromkeys([str(x).strip() for x in lst if str(x).strip()]))
        
        c["behavioral_markers"] = dd(bm)[:18]
        c["voice_notes"] = dd(vn)[:12]
        c["hard_limits"] = dd(hl)[:12]
        
        # Save to DB
        # Note: 'upsert_character' expects flat fields.
        # We need to serialize these lists into the columns.
        # But `schema.sql` had:
        # voice_notes TEXT
        # description TEXT
        # relationships TEXT (JSON)
        # current_status TEXT (JSON)
        
        # Where do 'behavioral_markers' and 'hard_limits' go?
        # My schema missed them!
        # I should store them in 'description' or add columns?
        # OR store a 'meta' JSON blob?
        # 'relationships' is JSON.
        
        # Workaround: serialize all these lists into 'description' or 'voice_notes' JSON?
        # Or Just put them in 'relationships' for now (hack)?
        # Or better: create a new PROFILE dict and dumping it into `voice_notes` column (renaming it conceptually to 'profile_json')?
        
        # I'll put them in `voice_notes` as a JSON string for now.
        
        profile_json = {
            "behavioral_markers": c["behavioral_markers"],
            "voice_notes": c["voice_notes"],
            "hard_limits": c["hard_limits"]
        }
        
        db.upsert_character(name, {
            "role": c.get("role"),
            "description": c.get("description"),
            "voice_notes": json.dumps(profile_json), # Storing JSON in text column
            "relationships": c.get("relationships", {}),
            "current_status": c.get("current_status", {})
        })

    return {"characters": db.get_all_characters()}


# ------------------------------------------------------------------
#  AUTO-UPDATE STATE
# ------------------------------------------------------------------
def parse_state_update_block(model_response: str) -> Optional[Dict[str, Any]]:
    """Parse UPDATE_STATE YAML block."""
    try:
        import yaml
        pattern = r"```yaml\n(.*?UPDATE_STATE:.*?)```"
        match = re.search(pattern, model_response, re.DOTALL)
        if match:
            extracted = yaml.safe_load(match.group(1))
            return extracted.get("UPDATE_STATE", {})
    except Exception:
        pass
    return None


def update_story_state(state_file: str, model_response: str, verbose: bool = True) -> Tuple[bool, str]:
    """Scans response, updates DB."""
    updates = parse_state_update_block(model_response)
    if not updates:
        return False, "No update."
    
    msg_parts = []
    
    if "current_time" in updates:
        db.set_kv("current_time", updates["current_time"])
        msg_parts.append(f"Time: {updates['current_time']}")
        
    if "current_location" in updates:
        db.set_kv("current_location", updates["current_location"])
        msg_parts.append(f"Loc: {updates['current_location']}")
        
    if "add_inventory" in updates:
        inv = db.get_kv("inventory", [])
        if updates["add_inventory"] not in inv:
            inv.append(updates["add_inventory"])
            db.set_kv("inventory", inv)
            msg_parts.append(f"+Inv: {updates['add_inventory']}")
            
    if "remove_inventory" in updates:
        inv = db.get_kv("inventory", [])
        if updates["remove_inventory"] in inv:
            inv.remove(updates["remove_inventory"])
            db.set_kv("inventory", inv)
            msg_parts.append(f"-Inv: {updates['remove_inventory']}")
            
    # Generic keys
    for k, v in updates.items():
        if k not in ["current_time", "current_location", "add_inventory", "remove_inventory"]:
             db.set_kv(k, v)

    msg = f"✅ State Advanced: {', '.join(msg_parts)}"
    if verbose: print(f"   🔄 {msg}")
    return True, msg


def strip_state_update_block(text: str) -> str:
    pattern = r"```yaml\n.*?UPDATE_STATE:.*?```\s*"
    return re.sub(pattern, "", text, flags=re.DOTALL).strip()


def strip_tribunal_scores(text: str) -> str:
    pattern = r"\[Tribunal Scores?:.*?\]"
    return re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
