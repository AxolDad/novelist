"""
migrate_json_to_sqlite.py — One-time migration script

Reads existing JSON state files and populates the new SQLite database.
Renames old JSON files to .bak after success.
"""

import json
import os
import shutil
import sys
from db_manager import init_db, set_kv, upsert_character, add_arc_item, log_scene
from config import META_DIR, STATE_FILE, CHAR_BIBLE_FILE, ARC_FILE

def migrate():
    print("🚀 Starting Migration to SQLite...")
    
    # Initialize DB (creates tables)
    init_db()
    
    # 1. World State
    if os.path.exists(STATE_FILE):
        print(f"   📦 Migrating {STATE_FILE}...")
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                ws = json.load(f)
            # Flatten or store keys individually? 
            # Strategy: Store top-level keys as KV pairs.
            for k, v in ws.items():
                set_kv(k, v)
            print("      -> Done.")
        except Exception as e:
            print(f"   ❌ Error reading world state: {e}")
    else:
        print(f"   ⚠️ {STATE_FILE} not found. Skipping.")
            
    # 2. Characters
    if os.path.exists(CHAR_BIBLE_FILE):
        print(f"   👥 Migrating {CHAR_BIBLE_FILE}...")
        try:
            with open(CHAR_BIBLE_FILE, 'r', encoding='utf-8') as f:
                cb = json.load(f)
            count = 0
            for name, data in cb.items():
                # Ensure dict structure
                if not isinstance(data, dict):
                    data = {"role": "Unknown", "description": str(data)}
                upsert_character(name, data)
                count += 1
            print(f"      -> {count} characters imported.")
        except Exception as e:
            print(f"   ❌ Error reading char bible: {e}")
    else:
        print(f"   ⚠️ {CHAR_BIBLE_FILE} not found. Skipping.")

    # 3. Arc Ledger
    if os.path.exists(ARC_FILE):
        print(f"   📜 Migrating {ARC_FILE}...")
        try:
            with open(ARC_FILE, 'r', encoding='utf-8') as f:
                arc = json.load(f)
                
            # Theme
            set_kv("arc_theme", arc.get("theme", "Unspecified"))
            
            # Lists
            counts = {"stake": 0, "promise": 0, "question": 0, "scene": 0}
            
            for s in arc.get("stakes", []):
                if isinstance(s, dict): s = s.get("description", str(s))
                add_arc_item("stake", str(s))
                counts["stake"] += 1
                
            for p in arc.get("promises_to_reader", []):
                if isinstance(p, dict): p = p.get("description", str(p))
                add_arc_item("promise", str(p))
                counts["promise"] += 1
                
            for q in arc.get("unresolved_questions", []):
                # Handle complex dicts in legacy files
                if isinstance(q, dict): q = q.get("question", q.get("name", str(q)))
                add_arc_item("question", str(q))
                counts["question"] += 1
                
            # Scene History
            for i, scene in enumerate(arc.get("scene_history", [])):
                title = scene.get("title", f"Scene {i+1}")
                summary = f"{scene.get('want','')} -> {scene.get('turn','')}"
                consequence = scene.get("consequence", "")
                
                log_scene(
                    title=title,
                    filename=f"migrated_{i+1:03d}_{title.replace(' ', '_')[:20]}", 
                    content="", # No content available in arc ledger
                    meta={
                        "summary": summary,
                        "consequence": consequence,
                        "characters_present": [],
                        "word_count": 0
                    }
                )
                counts["scene"] += 1
                
            print(f"      -> Imported {counts['stake']} stakes, {counts['promise']} promises, {counts['question']} questions, {counts['scene']} scenes.")
            
        except Exception as e:
             print(f"   ❌ Error reading arc ledger: {e}")
    else:
        print(f"   ⚠️ {ARC_FILE} not found. Skipping.")

    print("✅ Migration Complete.")
    
    # Rename legacy files (Safety First: Don't delete)
    print("   🔒 Backing up legacy JSON files...")
    for f in [STATE_FILE, CHAR_BIBLE_FILE, ARC_FILE]:
        if os.path.exists(f):
            dest = f + ".bak"
            try:
                shutil.move(f, dest)
                print(f"      Moved {f} -> {dest}")
            except Exception as e:
                print(f"      ⚠️ Failed to move {f}: {e}")

if __name__ == "__main__":
    migrate()
