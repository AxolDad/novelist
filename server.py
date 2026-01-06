"""
server.py - Central Database Server (API)

Wraps db_core.py with a FastAPI interface to provide a single point of failure (and locking) for SQLite.
Ensures thread-safe access to story.db.
"""

from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import db_core as db
import uvicorn
import logging
from logger import logger

app = FastAPI(title="Novelist Core Server")

# Pydantic models for structured input
class KVItem(BaseModel):
    key: str
    value: Any

class ArcItem(BaseModel):
    type: str # 'stake', 'promise', 'question'
    description: str

class CharacterProfile(BaseModel):
    name: str # The character name implies the key
    profile: Dict[str, Any]

class SceneLog(BaseModel):
    title: str
    filename: str
    content: str
    meta: Dict[str, Any]
    micro_outline: Optional[Dict[str, Any]] = None

class InitRequest(BaseModel):
    path: Optional[str] = None

# ------------------------------------------------------------------
#  KV STORE
# ------------------------------------------------------------------

@app.get("/kv/{key}")
def get_kv(key: str):
    val = db.get_kv(key)
    return {"value": val}

@app.post("/kv")
def set_kv(item: KVItem):
    try:
        db.set_kv(item.key, item.value)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Server KV Set Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ------------------------------------------------------------------
#  ARC ITEMS
# ------------------------------------------------------------------

@app.post("/arc")
def add_arc_item(item: ArcItem):
    try:
        db.add_arc_item(item.type, item.description)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Server Add Arc Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/arc/{type}")
def get_active_arc_items(type: str):
    items = db.get_active_arc_items(type)
    return {"items": items}

# ------------------------------------------------------------------
#  CHARACTERS
# ------------------------------------------------------------------

@app.get("/characters")
def get_all_characters():
    return db.get_all_characters()

@app.post("/characters/{name}")
def upsert_character(name: str, item: CharacterProfile):
    try:
        db.upsert_character(name, item.profile)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Server Upsert Character Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ------------------------------------------------------------------
#  SCENES
# ------------------------------------------------------------------

@app.post("/scenes")
def log_scene(scene: SceneLog):
    try:
        db.log_scene(
            filename=scene.filename,
            content=scene.content,
            meta=scene.meta,
            micro_outline=scene.micro_outline
        )
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Server Log Scene Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/scenes/recent")
def get_recent_scenes(limit: int = 5):
    history = db.get_recent_scene_history(limit)
    return {"history": history}

@app.get("/scenes/text")
def get_recent_scene_text_endpoint(limit: int = 2):
    """Get raw prose from recent scenes (for context)."""
    blocks = db.get_recent_scene_text(limit)
    return {"blocks": blocks}

@app.get("/scenes/count")
def get_scene_count():
    count = db.get_scene_count()
    return {"count": count}

@app.get("/scenes/words")
def get_total_word_count():
    total = db.get_total_word_count()
    return {"total": total}

@app.get("/state/dump")
def get_full_state_dump():
    return db.get_full_state_dump()

# ------------------------------------------------------------------
#  META / INIT
# ------------------------------------------------------------------

@app.post("/meta/init")
def init_db(req: InitRequest):
    try:
        db.init_db(req.path)
        return {"status": "initialized", "path": req.path}
    except Exception as e:
        logger.error(f"Server Init Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/health")
def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
