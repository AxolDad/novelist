"""
file_utils.py — File I/O Utilities

Handles all file operations including:
- JSON reading/writing with atomic saves
- Checkpoint management for crash recovery
- Directory management
- Scene file handling
"""

import json
import os
import re
import shutil
from typing import Any, Dict, List, Optional

from config import (
    MANIFEST_FILE,
    STATE_FILE,
    ARC_FILE,
    CHAR_BIBLE_FILE,
    META_DIR,
    SCENES_DIR,
    PLANNING_DIR,
    EXPORTS_DIR,
    LOGS_DIR,
    SNAPSHOTS_DIR,
    CHECKPOINT_DIR,
    LEGACY_CHECKPOINT_DIR,
)


def safe_read_json(path: str, default: Any) -> Any:
    """Safely read JSON file, returning default on any error."""
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def safe_write_json(path: str, data: Any) -> None:
    """Atomically write JSON file using temp file pattern."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def tail_excerpt(text: str, max_chars: int = 4000) -> str:
    """Return the tail of text, preferring end-of-scene changes."""
    if not text:
        return ""
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def ensure_project_dirs() -> None:
    """Create recommended folders without moving or renaming anything Beads depends on."""
    for d in [SCENES_DIR, META_DIR, PLANNING_DIR, EXPORTS_DIR, LOGS_DIR, SNAPSHOTS_DIR, CHECKPOINT_DIR]:
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass


def mirror_meta_files() -> None:
    """Copy key JSON files into /meta for convenient browsing (root files remain source of truth)."""
    ensure_project_dirs()
    for p in [MANIFEST_FILE, STATE_FILE, ARC_FILE, CHAR_BIBLE_FILE]:
        try:
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(META_DIR, os.path.basename(p)))
        except Exception:
            pass


# ------------------------------------------------------------------
#  CHECKPOINT MANAGEMENT (Crash Recovery)
# ------------------------------------------------------------------
def checkpoint_path(task_id: str) -> str:
    """Get the checkpoint file path for a task."""
    ensure_project_dirs()
    return os.path.join(CHECKPOINT_DIR, f"{task_id}.json")


def load_checkpoint(task_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Load checkpoint data for a task, checking both new and legacy locations."""
    if not task_id:
        return None

    # Try new location first
    path = checkpoint_path(task_id)
    if os.path.exists(path):
        data = safe_read_json(path, None)
        return data if isinstance(data, dict) else None

    # Back-compat: legacy /checkpoints
    legacy = os.path.join(LEGACY_CHECKPOINT_DIR, f"{task_id}.json")
    if os.path.exists(legacy):
        data = safe_read_json(legacy, None)
        return data if isinstance(data, dict) else None

    return None


def save_checkpoint(task_id: Optional[str], data: Dict[str, Any]) -> None:
    """Save checkpoint data for a task to both new and legacy locations."""
    if not task_id:
        return
    ensure_project_dirs()

    # Primary
    path = checkpoint_path(task_id)
    safe_write_json(path, data)

    # Legacy mirror (helps if you downgrade script later)
    try:
        os.makedirs(LEGACY_CHECKPOINT_DIR, exist_ok=True)
        legacy = os.path.join(LEGACY_CHECKPOINT_DIR, f"{task_id}.json")
        safe_write_json(legacy, data)
    except Exception:
        pass


def clear_checkpoint(task_id: Optional[str]) -> None:
    """Remove checkpoint files for a completed task."""
    if not task_id:
        return
    try:
        path = checkpoint_path(task_id)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    try:
        legacy = os.path.join(LEGACY_CHECKPOINT_DIR, f"{task_id}.json")
        if os.path.exists(legacy):
            os.remove(legacy)
    except Exception:
        pass


# ------------------------------------------------------------------
#  SCENE FILE MANAGEMENT
# ------------------------------------------------------------------
def list_completed_scene_files() -> List[str]:
    """
    Returns paths to completed scene files.
    - Primary location: /scenes (recommended)
    - Back-compat: also scans project root for legacy runs
    De-dupes by filename, preferring /scenes when duplicates exist.
    """
    candidates: List[str] = []

    for base in [SCENES_DIR, "."]:
        try:
            if not os.path.isdir(base):
                continue
            for fn in os.listdir(base):
                if re.match(r"^scene_\d+\.txt$", fn):
                    candidates.append(os.path.join(base, fn))
        except Exception:
            continue

    # Prefer SCENES_DIR version when both exist
    by_name: Dict[str, str] = {}
    for p in candidates:
        name = os.path.basename(p)
        if name not in by_name:
            by_name[name] = p
        else:
            # prefer scenes/ over root
            if os.path.dirname(p) == SCENES_DIR and os.path.dirname(by_name[name]) != SCENES_DIR:
                by_name[name] = p

    files = list(by_name.values())

    def num_key(path: str) -> int:
        m = re.match(r"^scene_(\d+)\.txt$", os.path.basename(path))
        return int(m.group(1)) if m else 0

    return sorted(files, key=num_key)


def load_recent_scene_context(n: int = 2, max_chars_each: int = 3500) -> str:
    """Load the last N scenes as context for continuity."""
    files = list_completed_scene_files()
    if not files:
        return ""
    recent = files[-n:]
    blocks = []
    for fn in recent:
        try:
            txt = open(fn, "r", encoding="utf-8").read()
            txt = tail_excerpt(txt, max_chars_each)
            blocks.append(f"\n--- {os.path.basename(fn)} (tail excerpt) ---\n{txt}\n")
        except Exception:
            pass
    return "\n".join(blocks).strip()
