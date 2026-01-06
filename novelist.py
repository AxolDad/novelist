"""
novelist.py — Main Story Generation Agent

Orchestrates the AI-powered novel writing system:
- Initializes project and Beads tasks
- Main agent loop for processing scenes
- Coordinates quality passes and state updates

All helper functions have been extracted to separate modules:
- config.py: Constants and configuration
- ollama_client.py: Ollama API communication
- beads_manager.py: Beads task management
- file_utils.py: File I/O utilities
- quality_passes.py: Style/subtext/drift enforcement
- state_manager.py: World state and arc ledger
- prompts.py: System prompts and builders
"""

import sys
import json
import os
import shutil
import time
import argparse
from typing import Any, Dict, Optional
import logging

# Import from modules
from config import (
    MANIFEST_FILE,
    STATE_FILE,
    ARC_FILE,
    CHAR_BIBLE_FILE,
    STYLES_MASTER_FILE,
    MACRO_OUTLINE_FILE,
    PROGRESS_FILE,
    OUTPUT_DIR,
    SCENES_DIR,
    MANUSCRIPT_FILE_DEFAULT,
    LOCAL_BREATH_SECONDS,
    PROSE_CONTEXT_SCENES,
    PROSE_CONTEXT_MAX_CHARS_EACH,
    STATE_EXCERPT_CHARS,
    WRITER_MODEL,
    CRITIC_MODEL,
    LLM_PROVIDER,
)

from ollama_client import (
    call_ollama,
    check_ollama_connection,
    extract_clean_json,
)

from beads_manager import (
    run_beads,
    force_sync,
    get_task_id,
    beads_all_work_closed,
)

from file_utils import (
    safe_read_json,
    safe_write_json,
    tail_excerpt,
    ensure_project_dirs,
    mirror_meta_files,
    load_checkpoint,
    save_checkpoint,
    clear_checkpoint,
    load_recent_scene_context,
)

from quality_passes import (
    lint_text,
    has_dialogue,
    enforce_style_lint,
    build_subtext_map,
    enforce_dialogue_subtext,
    detect_behavioral_drift,
    enforce_drift_fixes,
    sanitize_llm_output,
)

from state_manager import (
    seed_arc_ledger,
    ensure_arc_ledger_schema,
    update_arc_ledger,
    seed_character_bible,
    update_character_bible,
    compute_current_word_count,
    get_target_word_count,
    update_story_state,
    strip_state_update_block,
    strip_tribunal_scores,
)

from prompts import (
    critique_scene,
    select_best_draft,
    WRITER_FRAME_PROMPT,
    load_styles_master,
    build_structure_guidance,
    build_micro_outline,
)

import concurrent.futures


from manuscript_polisher import polish_manuscript

from story_architect import (
    generate_story_arc,
    build_memory_anchor,
    compress_for_prompt,
    generate_style_bible,
    load_style_bible,
    save_style_bible,
    style_bible_to_prompt,
    validate_progression,
    extract_scene_delta,
)

# ------------------------------------------------------------------
#  HUMAN-IN-THE-LOOP TIMEOUT
# ------------------------------------------------------------------
HUMAN_REVIEW_TIMEOUT = int(os.getenv("HUMAN_REVIEW_TIMEOUT", "300"))  # 5 minutes default

def input_with_timeout(prompt: str, timeout_seconds: int = HUMAN_REVIEW_TIMEOUT) -> Optional[str]:
    """
    Get user input with timeout. Returns None if timeout occurs.
    Works on Windows (no select.select on stdin).
    """
    import threading
    result = [None]
    input_received = threading.Event()
    
    def get_input():
        try:
            result[0] = input(prompt)
            input_received.set()
        except EOFError:
            result[0] = ""
            input_received.set()
    
    thread = threading.Thread(target=get_input, daemon=True)
    thread.start()
    
    # Wait for either input or timeout
    got_input = input_received.wait(timeout=timeout_seconds)
    
    if not got_input:
        return None  # Timeout
    return result[0]


def generate_ai_chapter_review(manuscript_path: str) -> str:
    """Generate an AI review of the chapter when human doesn't respond."""
    try:
        with open(manuscript_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Get last ~4000 chars (roughly the recent chapter)
        excerpt = content[-4000:] if len(content) > 4000 else content
        
        prompt = f"""Review this chapter excerpt briefly. Note 1-2 strengths and 1-2 areas for improvement.
Be concise (3-4 sentences max).

EXCERPT:
{excerpt}

OUTPUT: Brief review in plain text."""
        
        review = call_ollama([{"role": "user", "content": prompt}], model=CRITIC_MODEL)
        return review or "Auto-review unavailable. Continuing..."
    except Exception as e:
        return f"Auto-review skipped: {e}"


def generate_parallel_drafts(system_context: str, user_prompt: str) -> Optional[str]:
    """Generates 3 drafts with different temperatures and selects the best one."""
    messages = [
        {"role": "system", "content": system_context},
        {"role": "user", "content": user_prompt}
    ]
    
    # Temperatures: 0.7 (Safe), 0.9 (Creative), 1.1 (Chaotic/Innovative)
    temps = [0.7, 0.9, 1.1]
    
    print(f"   ⚖️  Drafting 3 variants in parallel (Temps: {temps})...")
    
    drafts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(call_ollama, messages, WRITER_MODEL, False, 32768, None, t)
            for t in temps
        ]
        
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                drafts.append(res)
    
    if not drafts:
        return None
        
    if len(drafts) == 1:
        return drafts[0]
        
    print(f"   🧐 Evaluating {len(drafts)} drafts via Editor-in-Chief...")
    selection = select_best_draft(drafts)
    idx = selection.get("best_draft_index", 1) - 1
    reason = selection.get("reasoning", "No valid reason provided.")
    
    # Safety Check
    if idx < 0 or idx >= len(drafts):
        idx = 0
        
    print(f"   🏆 Selected Draft {idx+1}: {reason[:100]}...")
    return drafts[idx]


# ------------------------------------------------------------------
#  PROJECT PATH CONFIGURATION
# ------------------------------------------------------------------
# Global paths (can be overridden by setup_project_paths)
PROJECT_PATH = None

def setup_project_paths(project_path: str) -> Dict[str, str]:
    """
    Override global config paths to use project-specific files.
    
    Args:
        project_path: Path to project folder (e.g., "projects/zero_buoyancy")
    
    Returns:
        Dict of path names to actual paths
    """
    global MANIFEST_FILE, STATE_FILE, ARC_FILE, CHAR_BIBLE_FILE
    global MACRO_OUTLINE_FILE, PROGRESS_FILE, OUTPUT_DIR, SCENES_DIR
    global MANUSCRIPT_FILE_DEFAULT, PROJECT_PATH
    
    # Normalize path for WSL/Cross-platform compatibility
    project_path = project_path.replace("\\", "/")
    PROJECT_PATH = project_path
    
    # Override all file paths
    import config
    config.MANIFEST_FILE = os.path.join(project_path, "story_manifest.json")
    config.STATE_FILE = os.path.join(project_path, "world_state.json")
    config.ARC_FILE = os.path.join(project_path, "arc_ledger.json")
    config.CHAR_BIBLE_FILE = os.path.join(project_path, "character_bible.json")
    config.MACRO_OUTLINE_FILE = os.path.join(project_path, "meta", "macro_outline.json")
    config.PROGRESS_FILE = os.path.join(project_path, "meta", "progress_ledger.json")
    config.OUTPUT_DIR = os.path.join(project_path, "outputs")
    config.SCENES_DIR = os.path.join(project_path, "outputs", "scenes")
    config.MANUSCRIPT_FILE_DEFAULT = os.path.join(project_path, "outputs", "manuscript.md")
    
    # Also update local copies
    MANIFEST_FILE = config.MANIFEST_FILE
    STATE_FILE = config.STATE_FILE
    ARC_FILE = config.ARC_FILE
    CHAR_BIBLE_FILE = config.CHAR_BIBLE_FILE
    MACRO_OUTLINE_FILE = config.MACRO_OUTLINE_FILE
    PROGRESS_FILE = config.PROGRESS_FILE
    OUTPUT_DIR = config.OUTPUT_DIR
    SCENES_DIR = config.SCENES_DIR
    MANUSCRIPT_FILE_DEFAULT = config.MANUSCRIPT_FILE_DEFAULT
    
    # Ensure directories exist
    os.makedirs(os.path.join(project_path, "meta", "checkpoints"), exist_ok=True)
    os.makedirs(config.SCENES_DIR, exist_ok=True)
    
    return {
        "manifest": config.MANIFEST_FILE,
        "world_state": config.STATE_FILE,
        "manuscript": config.MANUSCRIPT_FILE_DEFAULT,
    }


# ------------------------------------------------------------------
#  MACRO OUTLINE (Auto-plan additional scenes using Story Architect)
# ------------------------------------------------------------------
def ensure_macro_outline(
    manifest: Dict[str, Any], 
    world_state: Dict[str, Any], 
    arc_ledger: Dict[str, Any], 
    char_bible: Dict[str, Any],
    force_regenerate: bool = False
) -> Dict[str, Any]:
    """
    Auto-plans scenes using R1's Chain-of-Thought reasoning.
    Uses story_architect.generate_story_arc for proper plot progression.
    """
    existing = safe_read_json(MACRO_OUTLINE_FILE, None)
    
    # Only use existing if it has actual scenes AND we're not forcing regeneration
    if not force_regenerate and isinstance(existing, dict) and isinstance(existing.get("scenes"), list) and len(existing["scenes"]) > 0:
        return existing

    planning = manifest.get("planning", {}) or {}
    scene_word_target = int(planning.get("scene_word_target") or 0) or 1200
    
    # Calculate how many scenes we need
    target_wc = get_target_word_count(manifest)
    current_wc = compute_current_word_count(manifest, MANUSCRIPT_FILE_DEFAULT)
    words_remaining = max(target_wc - current_wc, 0)
    scenes_needed = max((words_remaining // scene_word_target) + 2, 5)
    
    print(f"   🧠 Using Story Architect to reason through {scenes_needed}-scene arc...")
    
    # Use the new story architect for proper reasoning
    arc_data = generate_story_arc(
        manifest=manifest,
        world_state=world_state,
        arc_ledger=arc_ledger,
        target_scenes=scenes_needed
    )
    
    # Transform arc_data into macro outline format (add target_words, ensure index exists)
    scenes = arc_data.get("scenes", [])
    for i, scene in enumerate(scenes):
        scene["index"] = scene.get("index", i + 1)
        scene["target_words"] = scene.get("target_words", scene_word_target)
        scene["chapter"] = scene.get("chapter", (i // 3) + 1)
    
    # Store arc metadata alongside scenes
    data = {
        "core_tension": arc_data.get("core_tension", ""),
        "chosen_endpoint": arc_data.get("chosen_endpoint", "ambiguity"),
        "endpoint_description": arc_data.get("endpoint_description", ""),
        "midpoint_reversal": arc_data.get("midpoint_reversal", ""),
        "scenes": scenes
    }
    
    print(f"   ✅ Arc generated: {data['chosen_endpoint']} ending with {len(scenes)} scenes")
    print(f"      Core tension: {data['core_tension'][:80]}..." if data['core_tension'] else "")
    
    safe_write_json(MACRO_OUTLINE_FILE, data)
    safe_write_json(PROGRESS_FILE, {"next_scene_index": 1})
    return data


def seed_next_scene_task_if_needed(
    manifest: Dict[str, Any], 
    world_state: Dict[str, Any], 
    arc_ledger: Dict[str, Any], 
    char_bible: Dict[str, Any]
) -> bool:
    """
    When there are no remaining Beads tasks but the word target isn't met, 
    auto-create the next Scene task. Returns True if a task was created.
    """
    target_wc = get_target_word_count(manifest)
    current_wc = compute_current_word_count(manifest, MANUSCRIPT_FILE_DEFAULT)
    if current_wc >= target_wc:
        return False

    prog = safe_read_json(PROGRESS_FILE, {"next_scene_index": 1})
    next_idx = int(prog.get("next_scene_index") or 1)

    # Try to get existing macro outline first
    macro = ensure_macro_outline(manifest, world_state, arc_ledger, char_bible, force_regenerate=False)
    scenes = macro.get("scenes") or []
    
    # Find the next scene by index
    next_scene = None
    for s in scenes:
        try:
            if int(s.get("index") or 0) == next_idx:
                next_scene = s
                break
        except Exception:
            continue
    
    # If no scene found at that index, we've exhausted the outline - regenerate!
    if not next_scene:
        print(f"   🔄 Scene index {next_idx} not found in outline. Regenerating macro outline...")
        # Reset progress and force regeneration
        safe_write_json(PROGRESS_FILE, {"next_scene_index": 1})
        next_idx = 1
        
        # Force regenerate the macro outline
        macro = ensure_macro_outline(manifest, world_state, arc_ledger, char_bible, force_regenerate=True)
        scenes = macro.get("scenes") or []
        
        if not scenes:
            print("   ❌ Could not generate macro outline. Manual intervention may be needed.")
            return False
        
        # Get the first scene from the new outline
        next_scene = scenes[0] if scenes else None
        if not next_scene:
            return False

    title = next_scene.get("title") or f"Scene {next_idx}"
    desc = next_scene.get("goal") or f"Advance macro beat: {next_scene.get('macro_beat', '')}"
    
    print(f"   🎯 Seeding: {title}")
    print(f"      Goal: {desc[:80]}...")
    
    created = run_beads(['create', title, desc])
    if created is None:
        print(f"   ❌ Failed to create beads task for {title}")
        return False

    prog["next_scene_index"] = next_idx + 1
    safe_write_json(PROGRESS_FILE, prog)
    force_sync()
    time.sleep(LOCAL_BREATH_SECONDS)
    print(f"🧩 Auto-seeded {title} to keep writing toward target words.")
    return True


# ------------------------------------------------------------------
#  SYSTEM HEALTH CHECK
# ------------------------------------------------------------------
def system_health_check(manifest: Dict[str, Any]) -> None:
    """Run system health check on startup."""
    print("\n🩺 SYSTEM HEALTH CHECK")
    
    # 1) Ollama
    if check_ollama_connection():
        print("   ✅ Ollama reachable.")
    else:
        print("   ❌ Ollama NOT reachable at http://localhost:11434")
        print("      Fix: start ollama server, confirm port, or adjust OLLAMA_URL.")
        sys.exit(1)

    # 2) Required files
    required = [MANIFEST_FILE, STATE_FILE, ARC_FILE, CHAR_BIBLE_FILE]
    missing = [p for p in required if not os.path.exists(p)]
    if missing:
        print(f"   ❌ Missing required files: {missing}")
        sys.exit(1)
    print("   ✅ Required files present.")

    # 3) Story title
    title = manifest.get("title") or "(untitled)"
    print(f"   📘 Story: {title}")

    # 4) Word count progress
    current_wc = compute_current_word_count(manifest, MANUSCRIPT_FILE_DEFAULT)
    target_wc = get_target_word_count(manifest)
    pct = (current_wc / target_wc * 100.0) if target_wc > 0 else 0.0
    print(f"   ✍️  Current word count: {current_wc:,}")
    print(f"   🎯 Target word count:  {target_wc:,}")
    print(f"   📈 Progress:           {pct:.1f}%\n")


# ------------------------------------------------------------------
#  NOVEL FINALIZATION (Polishing before completion)
# ------------------------------------------------------------------
def finalize_novel(manuscript_path: str, manifest: Dict[str, Any]) -> str:
    """
    Run final polishing pass before signaling novel completion.
    
    Uses The Architect (DeepSeek R1) for structural analysis and organization:
    - Organizes scenes into chapters
    - Cleans formatting artifacts
    - Creates publication-ready export
    
    Returns path to polished manuscript.
    """
    print("\n" + "="*60)
    print("🏆 NOVEL COMPLETION SEQUENCE")
    print("="*60)
    
    # Run manuscript polisher
    polished_path = polish_manuscript(
        manuscript_path=manuscript_path,
        manifest=manifest,
        verbose=True
    )
    
    if polished_path:
        print(f"\n📗 Final manuscript ready: {polished_path}")
    
    print("="*60 + "\n")
    return polished_path


# ------------------------------------------------------------------
#  INITIALIZATION LOGIC
# ------------------------------------------------------------------
def init_project() -> None:
    """Initialize project directories and Beads tasks."""
    ensure_project_dirs()
    mirror_meta_files()

    if not shutil.which('bd'):
        print("❌ Error: 'bd' tool not found.")
        sys.exit(1)

    if os.path.exists(".beads"):
        force_sync()
        time.sleep(LOCAL_BREATH_SECONDS)
    else:
        print("🚀 Initializing new Beads project...")
        run_beads(['init'])
        time.sleep(LOCAL_BREATH_SECONDS)

    if not os.path.exists(MANIFEST_FILE):
        print(f"❌ Error: {MANIFEST_FILE} missing.")
        sys.exit(1)

    with open(MANIFEST_FILE, 'r', encoding="utf-8") as f:
        manifest = json.load(f)

    if not os.path.exists(STATE_FILE):
        safe_write_json(STATE_FILE, manifest.get('world_state', {}))

    if not os.path.exists(ARC_FILE):
        safe_write_json(ARC_FILE, seed_arc_ledger(manifest))

    if not os.path.exists(CHAR_BIBLE_FILE):
        ws = safe_read_json(STATE_FILE, {})
        safe_write_json(CHAR_BIBLE_FILE, seed_character_bible(ws))

    # Seed styles master if missing
    if not os.path.exists(STYLES_MASTER_FILE):
        safe_write_json(STYLES_MASTER_FILE, load_styles_master())

    list_json = run_beads(['list', '--json'])
    if not list_json or list_json.strip() == "[]":
        print(f"📚 Seeding Scenes for: {manifest.get('title','(untitled)')}")
        prev_id = None
        scene_count = 1

        for act in manifest.get('acts', []):
            scenes = act.get('scenes', [])
            for scene_desc in scenes:
                title = f"Scene {scene_count}"
                print(f"   Creating {title}...")
                run_beads(['create', title, scene_desc])
                force_sync()
                time.sleep(LOCAL_BREATH_SECONDS)

                task_id = None
                for _ in range(7):
                    tasks_json = run_beads(['list', '--json'])
                    if tasks_json:
                        try:
                            tasks = json.loads(tasks_json)
                            task_id = get_task_id(tasks, title)
                            if task_id:
                                break
                        except Exception:
                            pass
                    time.sleep(1.2)

                if task_id:
                    if prev_id:
                        run_beads(['dep', 'add', prev_id, task_id])
                        force_sync()
                        time.sleep(LOCAL_BREATH_SECONDS)
                        print(f"     🔗 Linked {prev_id} -> {task_id}")
                    prev_id = task_id
                    scene_count += 1
                else:
                    print(f"   ⚠️ TIMEOUT: Could not find ID for {title}")


# ------------------------------------------------------------------
#  MAIN AGENT LOOP
# ------------------------------------------------------------------
def draft_loop(manifest: Dict[str, Any]) -> None:
    """
    Main agent loop.
    Continuously checks for Beads tasks and orchestrates the writing process.
    """
    # Ensure we are in a valid project state
    init_project()

    # Configure logging
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Clear old log file on fresh start
    log_file = os.path.join(log_dir, "novelist.log")
    if os.path.exists(log_file):
        try:
            os.remove(log_file)
        except:
            pass

    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        force=True
    )
    
    # Also log to stdout
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('%(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

    logging.info("🚀 Novelist Agent Starting...")

    manifest = safe_read_json(MANIFEST_FILE, {})
    system_health_check(manifest)
    system_health_check(manifest)

    print("\n✅ Project Loaded. Starting Agent Loop...")

    while True:
        ready_json = run_beads(['ready', '--json'])
        ready_tasks = []
        if ready_json:
            try:
                ready_tasks = json.loads(ready_json)
            except Exception:
                ready_tasks = []

        if not ready_tasks:
            # Attempt to auto-seed the next scene if we're not done
            # Load basic state needed for seeding decision
            try:
                ws_seed = safe_read_json(STATE_FILE, {})
                arc_seed = safe_read_json(ARC_FILE, seed_arc_ledger(manifest))
                char_seed = safe_read_json(CHAR_BIBLE_FILE, seed_character_bible(ws_seed))
                
                if seed_next_scene_task_if_needed(manifest, ws_seed, arc_seed, char_seed):
                    continue
            except Exception as e:
                print(f"   ⚠️ Auto-seed check failed: {e}")

            print("   ...Syncing database to check for new work...")
            force_sync()
            time.sleep(LOCAL_BREATH_SECONDS)

            status = run_beads(['status', '--json'])

            # Completion condition: All tasks closed
            if status and beads_all_work_closed(status):
                finalize_novel(MANUSCRIPT_FILE_DEFAULT, manifest)
                
                # Log word count for record
                current_wc = compute_current_word_count(manifest, MANUSCRIPT_FILE_DEFAULT)
                target_wc = get_target_word_count(manifest)
                print(f"🏆 NOVEL COMPLETE (All tasks closed). Final Word Count: {current_wc}/{target_wc}")
                break


            current_wc = compute_current_word_count(manifest, MANUSCRIPT_FILE_DEFAULT)
            target_wc = get_target_word_count(manifest)
            if current_wc >= target_wc:
                finalize_novel(MANUSCRIPT_FILE_DEFAULT, manifest)
                print("🏆 WORD TARGET MET. No ready scenes in Beads; stopping.")
                break

            print("💤 Waiting for work... (Ctrl+C to stop)")
            time.sleep(2.0)
            continue

        task = ready_tasks[0]
        title = task.get('Title') or task.get('title') or "Untitled Scene"
        task_id = task.get('ID') or task.get('id')
        desc = task.get('Desc') or task.get('desc') or ""

        print(f"\n🎬 ACTION: {title} (ID: {task_id})")
        time.sleep(LOCAL_BREATH_SECONDS)

        # Load state / ledgers
        world_state = safe_read_json(STATE_FILE, {})
        manifest = safe_read_json(MANIFEST_FILE, {})
        arc_ledger = safe_read_json(ARC_FILE, seed_arc_ledger(manifest))
        arc_ledger = ensure_arc_ledger_schema(arc_ledger, manifest)
        char_bible = safe_read_json(CHAR_BIBLE_FILE, seed_character_bible(world_state))

        # Load checkpoint if exists (crash-resume)
        ckpt = load_checkpoint(task_id) or {}
        if ckpt and ckpt.get("task_id") == task_id:
            print("   ♻️  Checkpoint found. Resuming in-progress scene...")

        # Optional Story Bible text + FIX #8: Include character bible
        story_bible_text = ""
        if os.path.exists("story_bible.txt"):
            try:
                story_bible_text = open("story_bible.txt", "r", encoding="utf-8").read().strip()
            except Exception:
                story_bible_text = ""
        
        # FIX #8: Add character bible constraints to story context
        char_bible_block = []
        char_bible_chars = char_bible.get("characters", {})
        for char_name, char_data in char_bible_chars.items():
            constraints = []
            if char_data.get("behavioral_markers"):
                constraints.append(f"  Behaviors: {', '.join(char_data['behavioral_markers'][:3])}")
            if char_data.get("voice_notes"):
                constraints.append(f"  Voice: {', '.join(char_data['voice_notes'][:3])}")
            if char_data.get("hard_limits"):
                constraints.append(f"  HARD LIMITS: {', '.join(char_data['hard_limits'])}")
            if constraints:
                char_bible_block.append(f"[{char_name}]\n" + "\n".join(constraints))
        
        if char_bible_block:
            story_bible_text += "\n\n═══ CHARACTER BIBLE (DO NOT VIOLATE) ═══\n" + "\n\n".join(char_bible_block)

        # Rolling prose context
        recent_prose = load_recent_scene_context(PROSE_CONTEXT_SCENES, PROSE_CONTEXT_MAX_CHARS_EACH)

        # Load macro outline to get scene-specific arc info (BEFORE/AFTER states)
        macro_outline = safe_read_json(MACRO_OUTLINE_FILE, {})
        scene_arc_info = None
        if macro_outline.get("scenes"):
            # Try to find the current scene in the macro outline by title
            for s in macro_outline["scenes"]:
                scene_title = s.get("title", "").lower()
                if scene_title and scene_title in title.lower():
                    scene_arc_info = s
                    break
            # If not found by title, use current index from progress
            if not scene_arc_info:
                prog = safe_read_json(PROGRESS_FILE, {"next_scene_index": 1})
                current_idx = max(1, prog.get("next_scene_index", 1) - 1)  # Current scene is one before next
                for s in macro_outline["scenes"]:
                    if s.get("index") == current_idx:
                        scene_arc_info = s
                        break

        # Load style bible for voice consistency
        style_bible = load_style_bible()

        # MICRO-OUTLINE (Beat Sheet) — resume if present
        micro_outline = ckpt.get("micro_outline") if isinstance(ckpt.get("micro_outline"), dict) else None
        if not micro_outline:
            print("   🧭 Building micro-outline with arc info...")
            
            # P1 FIX #6: Extract previous scene summaries for anti-repetition
            scene_history = arc_ledger.get("scene_history", [])
            prev_summaries = [s.get("consequence", "") for s in scene_history[-3:] if s.get("consequence")]
            
            micro_outline = build_micro_outline(
                scene_goal=desc, 
                arc_ledger=arc_ledger, 
                char_bible=char_bible, 
                world_state=world_state,
                scene_arc_info=scene_arc_info,
                previous_scene_summaries=prev_summaries
            )
            ckpt = {
                "task_id": task_id,
                "title": title,
                "desc": desc,
                "micro_outline": micro_outline,
                "draft": "",
                "lint_done": False,
                "subtext_done": False,
                "drift_done": False,
                "tribunal_attempts": 0
            }
            save_checkpoint(task_id, ckpt)
            time.sleep(LOCAL_BREATH_SECONDS)
        else:
            print("   🧭 Using micro-outline from checkpoint.")

        # Build compressed Memory Anchor for context efficiency
        scene_history = arc_ledger.get("scene_history", [])
        current_scene_idx = len(scene_history) + 1
        memory_anchor = build_memory_anchor(
            world_state=world_state,
            arc_ledger=arc_ledger,
            recent_prose=recent_prose,
            current_scene_index=current_scene_idx
        )
        compressed_context = compress_for_prompt(memory_anchor)

        # Build system context with style bible and compressed state
        style_bible_prompt = style_bible_to_prompt(style_bible)
        
        # P0 FIX #2: Substitute world state placeholders in WRITER_FRAME_PROMPT
        # This enables anti-loop (current_time) and physics (posture) checks
        writer_prompt_with_state = WRITER_FRAME_PROMPT
        writer_prompt_with_state = writer_prompt_with_state.replace(
            "{{current_time}}", world_state.get("current_time", "Unknown")
        )
        writer_prompt_with_state = writer_prompt_with_state.replace(
            "{{posture}}", world_state.get("posture", "Unknown")
        )
        
        # Extract protagonist info from manifest/world_state for generic anchoring
        characters = world_state.get("characters", {})
        protagonist_name = list(characters.keys())[0] if characters else "Protagonist"
        protagonist_info = characters.get(protagonist_name, {})
        protagonist_role = manifest.get("style", {}).get("protagonist_role", "the main character")
        
        # FIX #2: Extract POV from manifest
        pov = manifest.get("style", {}).get("pov", "third_limited")
        writer_prompt_with_state = writer_prompt_with_state.replace(
            "{{pov}}", pov
        )
        
        # FIX #3: Build character relationships summary
        char_relationships = []
        for char_name, char_data in characters.items():
            role = char_data.get("role", char_data.get("status", "Unknown role"))
            char_relationships.append(f"- {char_name}: {role}")
        char_relationships_text = "\n".join(char_relationships) if char_relationships else "No characters defined"
        writer_prompt_with_state = writer_prompt_with_state.replace(
            "{{character_relationships}}", char_relationships_text
        )
        
        # Replace story-agnostic placeholders (P1 Fix #1 partial)
        writer_prompt_with_state = writer_prompt_with_state.replace(
            "{{protagonist_name}}", protagonist_name
        )
        writer_prompt_with_state = writer_prompt_with_state.replace(
            "{{protagonist_role}}", protagonist_role
        )
        
        system_context = f"""{writer_prompt_with_state}

{style_bible_prompt}

STORY BIBLE (if present):
{story_bible_text}

COMPRESSED STORY STATE:
{compressed_context}

RECENT PROSE (for voice + continuity; do not restate):
{tail_excerpt(recent_prose, 1500) if recent_prose else "No previous scenes"}

SCENE ARC INFO (from Story Architect):
Before State: {micro_outline.get('before_state', 'To be established')}
After State: {micro_outline.get('after_state', 'Must be DIFFERENT from before')}
Irreversible Change: {micro_outline.get('irreversible_change', 'Something must change permanently')}
"""

        # Structural guidance (weighted blend)
        try:
            system_context += "\n\n" + build_structure_guidance(manifest) + "\n"
        except Exception:
            pass

        # WRITE SCENE (Draft) — resume if present
        draft = ckpt.get("draft") if isinstance(ckpt.get("draft"), str) and ckpt.get("draft").strip() else None
        if not draft:
            # Extract key info from micro_outline
            before_state = micro_outline.get("before_state", "Unknown")
            after_state = micro_outline.get("after_state", "Must be DIFFERENT")
            irreversible_change = micro_outline.get("irreversible_change", "Something permanent")
            
            draft_prompt = f"""
<think>
Before writing, reason through:
1. The character starts in: {before_state}
2. The character MUST end in: {after_state}
3. The irreversible change is: {irreversible_change}
4. What specific moments will show this transformation?
</think>

Now write {title}.

SCENE GOAL: {desc}

MICRO-OUTLINE (must follow):
{json.dumps(micro_outline, indent=2)}

CRITICAL REQUIREMENTS:
- The BEFORE STATE must be established at the scene's opening
- The AFTER STATE must be achieved by scene's end (DIFFERENT from before!)
- Hit want → obstacle → turn → consequence clearly
- End on consequence that CANNOT BE UNDONE
- Show psychological complexity through action, not labels

⚠️ IF THE SCENE ENDS THE SAME AS IT STARTED, YOU HAVE FAILED.
Something must change permanently.

Return ONLY the scene prose (no tags, no commentary).
"""
            draft = generate_parallel_drafts(system_context, draft_prompt)

            if not draft:
                print("   ❌ Failed to generate draft. Retrying loop...")
                time.sleep(2.0)
                continue

            # Sanitize draft to strip any meta-commentary
            draft = sanitize_llm_output(draft)
            # Update state from initial draft's UPDATE_STATE block (BEFORE stripping)
            update_story_state(STATE_FILE, draft, verbose=True)
            # Now strip scores and state blocks for clean prose storage
            draft = strip_tribunal_scores(strip_state_update_block(draft))
            
            ckpt["draft"] = draft
            save_checkpoint(task_id, ckpt)
            time.sleep(LOCAL_BREATH_SECONDS)
        else:
            print("   ✍️  Using draft from checkpoint.")
            time.sleep(LOCAL_BREATH_SECONDS)

        # ENFORCED QUALITY PASSES (checkpoint-aware)
        lint = lint_text(draft)
        if (not ckpt.get("lint_done")) and lint.get("issue_count", 0) > 0:
            print(f"   🧽 Style lint found {lint['issue_count']} issue groups. Enforcing cleanup...")
            draft = enforce_style_lint(draft, lint, system_context)
            ckpt["draft"] = draft
            ckpt["lint_done"] = True
            save_checkpoint(task_id, ckpt)
            time.sleep(LOCAL_BREATH_SECONDS)

        if (not ckpt.get("subtext_done")) and has_dialogue(draft):
            print("   🗣️  Dialogue detected. Building subtext map...")
            smap = build_subtext_map(draft, world_state, char_bible)
            if smap:
                print("   🧠 Enforcing subtext rewrite...")
                draft = enforce_dialogue_subtext(draft, smap, system_context)
                ckpt["draft"] = draft
                ckpt["subtext_done"] = True
                save_checkpoint(task_id, ckpt)
                time.sleep(LOCAL_BREATH_SECONDS)

        if not ckpt.get("drift_done"):
            print("   🧪 Running character drift check...")
            drift = detect_behavioral_drift(draft, char_bible, world_state)
            if drift.get("drift_found"):
                print("   🧷 Drift found. Enforcing consistency rewrite...")
                draft = enforce_drift_fixes(draft, drift, system_context)
            ckpt["draft"] = draft
            ckpt["drift_done"] = True
            save_checkpoint(task_id, ckpt)
            time.sleep(LOCAL_BREATH_SECONDS)

        # TRIBUNAL LOOP (3-Reviewer Critic Model) — resume attempt count
        attempts = int(ckpt.get("tribunal_attempts") or 0)
        scores = [0, 0, 0]  # [prose, redundancy, arc]
        
        # Build story context for Arc Critic
        scene_history = arc_ledger.get("scene_history", [])
        story_context = " | ".join([
            f"Scene {i+1}: {s.get('consequence', 'N/A')}" 
            for i, s in enumerate(scene_history[-5:])
        ]) if scene_history else "This is the first scene."
        
        # FIX #6: Revision Memory Chain - track what was tried
        revision_history = []
        
        while True:
            attempts += 1
            review = critique_scene(draft, story_context=story_context, scene_count=len(scene_history))
            # Safely extract scores with fallback to 50 (not 0) if None/invalid
            def safe_score(val, default=50):
                if val is None:
                    return default
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return default
            scores = [
                safe_score(review.get('prose_score')), 
                safe_score(review.get('redundancy_score')), 
                safe_score(review.get('arc_score'))
            ]
            print(f"   📊 Tribunal Scores: Prose={scores[0]} | Redundancy={scores[1]} | Arc={scores[2]} (Attempt {attempts})")

            ckpt["tribunal_attempts"] = attempts
            ckpt["draft"] = draft
            save_checkpoint(task_id, ckpt)

            if all(s >= 90 for s in scores):
                print("   ✅ ALL THREE CRITICS SATISFIED.")
                break

            if attempts > 3:
                print("   ⚠️ MAX REVISIONS REACHED. FORCING PROGRESS.")
                break

            # Extract actionable feedback from each reviewer
            prose_fix = review.get('prose_fix', "Improve sensory details.")
            redundancy_fix = review.get('redundancy_fix', "Remove clichés and filter words.")
            arc_fix = review.get('arc_fix', "Ensure scene advances the story.")
            priority_fix = review.get('priority_fix', prose_fix)
            irreversible = review.get('irreversible_change', "Not specified")
            
            # FIX #6: Record this attempt in revision history
            revision_history.append({
                "attempt": attempts,
                "scores": {"prose": scores[0], "redundancy": scores[1], "arc": scores[2]},
                "priority_issue": priority_fix[:100],  # Truncate for prompt efficiency
                "lowest_score": min(zip(["prose", "redundancy", "arc"], scores), key=lambda x: x[1])[0]
            })
            
            # Build revision history block for prompt
            revision_memory_block = ""
            if len(revision_history) > 1:
                revision_memory_block = "\n═══ REVISION HISTORY (WHAT WAS TRIED) ═══\n"
                for rh in revision_history[:-1]:  # All except current
                    revision_memory_block += f"Attempt {rh['attempt']}: Scores P={rh['scores']['prose']}/R={rh['scores']['redundancy']}/A={rh['scores']['arc']} | Issue: {rh['priority_issue'][:50]}\n"
                revision_memory_block += "\n⚠️ DO NOT repeat failed approaches. Try something NEW.\n"
            
            lint2 = lint_text(draft)

            revision_prompt = f"""
TRIBUNAL FEEDBACK (3 Expert Reviewers):

📝 PROSE CRITIC (Score: {scores[0]}/100):
{prose_fix}

🔁 REDUNDANCY CRITIC (Score: {scores[1]}/100):
{redundancy_fix}

📈 ARC CRITIC (Score: {scores[2]}/100):
{arc_fix}

⚡ PRIORITY FIX (Most Important):
{priority_fix}

📌 Current Irreversible Change: {irreversible}
{revision_memory_block}
CURRENT LINT ISSUES:
{json.dumps(lint2, indent=2)}

MICRO-OUTLINE (must still follow):
{json.dumps(micro_outline, indent=2)}

TASK:
COMPLETELY REWRITE the scene addressing the PRIORITY FIX first, then the other feedback.
- Apply the specific prose improvements suggested
- Remove the exact clichés/filter words quoted
- Ensure arc continuity as described
{"- IMPORTANT: Previous revision attempts failed. Try a DIFFERENT approach this time." if len(revision_history) > 1 else ""}

CRITICAL CONSTRAINTS:
⚠️ Do NOT include "[Tribunal Scores: ...]" or any meta-commentary in output.
⚠️ Character posture is: {world_state.get('posture', 'unknown')} — physics must match.
⚠️ Current time is: {world_state.get('current_time', 'unknown')} — do not rewrite this timestamp.
⚠️ After prose, include UPDATE_STATE YAML block to advance time.

Return ONLY revised scene text (plus UPDATE_STATE block at end).
"""
            print("   🔄 REVISING...")
            revised = call_ollama([
                {"role": "system", "content": system_context},
                {"role": "user", "content": revision_prompt},
                {"role": "user", "content": f"SCENE:\n{draft}"}
            ], model=WRITER_MODEL)

            if revised:
                # P2 FIX #5: Update state after each revision (BEFORE stripping)
                update_story_state(STATE_FILE, revised, verbose=False)
                
                # P0 FIX #3: NOW strip scores and meta-commentary for clean prose
                revised = strip_tribunal_scores(strip_state_update_block(revised))
                
                draft = revised
                ckpt["draft"] = draft
                save_checkpoint(task_id, ckpt)

            time.sleep(LOCAL_BREATH_SECONDS)

        # UPDATE WORLD STATE (JSON only) — use tail excerpt for better accuracy
        update_prompt = f"""
Return JSON ONLY.

Update world state based on the scene.
Keep it conservative: only what clearly changed.

SCENE (tail excerpt):
{tail_excerpt(draft, STATE_EXCERPT_CHARS)}

CURRENT STATE:
{json.dumps(world_state, indent=2)}

OUTPUT FORMAT:
{{
  "current_time": "... (if changed)",
  "current_location": "... (if changed)",
  "inventory_add": ["..."],
  "inventory_remove": ["..."],
  "characters": {{
     "<Name>": {{
        "status": "... (brief, observational)",
        "location": "... (if changed)"
     }}
  }}
}}
"""
        new_state_str = call_ollama([{"role": "user", "content": update_prompt}], model=WRITER_MODEL, json_mode=True)
        new_state = extract_clean_json(new_state_str)

        if new_state:
            try:
                inv_add = new_state.pop("inventory_add", [])
                inv_remove = set([s.lower() for s in new_state.pop("inventory_remove", []) if isinstance(s, str)])
                if inv_add:
                    world_state.setdefault("inventory", [])
                    for it in inv_add:
                        if it not in world_state["inventory"]:
                            world_state["inventory"].append(it)
                if inv_remove:
                    world_state.setdefault("inventory", [])
                    world_state["inventory"] = [it for it in world_state["inventory"] if it.lower() not in inv_remove]

                for k, v in new_state.items():
                    if k == "characters" and isinstance(v, dict):
                        world_state.setdefault("characters", {})
                        for cname, cinfo in v.items():
                            world_state["characters"].setdefault(cname, {})
                            if isinstance(cinfo, dict):
                                world_state["characters"][cname].update(cinfo)
                        world_state[k] = v

                safe_write_json(STATE_FILE, world_state)
                print("🌍 World State Updated.")
            except Exception:
                pass
        
        # ANTI-LOOP: Also parse any UPDATE_STATE block from the draft itself
        # This allows the model to explicitly advance time/location
        update_story_state(STATE_FILE, draft, verbose=True)

        time.sleep(LOCAL_BREATH_SECONDS)

        # Define filename early for DB logging
        filename = f"{title.replace(' ', '_').lower()}.txt"

        # UPDATE ARC LEDGER + CHARACTER BIBLE (long-arc memory)
        # DB-backed persistence (JSON writes disabled)
        arc_ledger = update_arc_ledger(arc_ledger, title, micro_outline, draft, filename=filename)
        # safe_write_json(ARC_FILE, arc_ledger)
        
        char_bible = update_character_bible(char_bible, draft, world_state)
        # safe_write_json(CHAR_BIBLE_FILE, char_bible)
        mirror_meta_files()

        # SAVE OUTPUTS
        ensure_project_dirs()

        output_cfg = (manifest.get("output", {}) or {})
        mode = (output_cfg.get("mode") or "manuscript").lower()
        manuscript_path = output_cfg.get("manuscript_file") or MANUSCRIPT_FILE_DEFAULT
        write_scene_files = bool(output_cfg.get("write_scene_files", False))
        also_write_legacy_root = bool(output_cfg.get("write_legacy_root_scene_files", True))

        # Ensure dirs
        try:
            os.makedirs(os.path.dirname(manuscript_path) or ".", exist_ok=True)
        except Exception:
            pass
        try:
            os.makedirs(SCENES_DIR, exist_ok=True)
        except Exception:
            pass

        # filename already defined above

        # Append to single manuscript (default)
        if mode in ("manuscript", "both"):
            try:
                header_needed = (not os.path.exists(manuscript_path)) or os.path.getsize(manuscript_path) == 0
                with open(manuscript_path, "a", encoding="utf-8") as mf:
                    if header_needed:
                        mf.write(f"# {manifest.get('title','(untitled)')}\n\n")
                    mf.write("\n---\n\n")
                    mf.write(f"## {title}\n\n")
                    # Clean the draft: remove tribunal scores and state update blocks
                    clean_draft = strip_tribunal_scores(strip_state_update_block(draft.strip()))
                    mf.write(clean_draft + "\n")
                print(f"📚 Appended to manuscript: {manuscript_path}")
            except Exception:
                pass

        # Optional per-scene files (organized)
        if mode in ("scene_files", "both") or write_scene_files:
            scene_path = os.path.join(SCENES_DIR, filename)
            try:
                with open(scene_path, "w", encoding="utf-8") as f:
                    f.write(draft)
                print(f"✅ Scene file saved to {scene_path}")
            except Exception:
                pass

            # Back-compat: also write to project root
            if also_write_legacy_root:
                try:
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(draft)
                except Exception:
                    pass

        # CLOSE TASK & SYNC
        if task_id:
            run_beads(['close', task_id])
        force_sync()
        time.sleep(LOCAL_BREATH_SECONDS)

        # Checkpoint is no longer needed after successful completion
        clear_checkpoint(task_id)

        print(f"✅ Scene Complete. Saved to {filename}")
        
        # FIX #10: Progressive Human Review - Chapter Checkpoints
        CHAPTER_SIZE = 5  # Scenes per chapter
        CHECKPOINT_ENABLED = True  # Set to False to disable interactive checkpoints
        
        current_scene_count = len(arc_ledger.get("scene_history", [])) + 1
        current_chapter = (current_scene_count - 1) // CHAPTER_SIZE
        is_chapter_end = current_scene_count % CHAPTER_SIZE == 0
        
        if CHECKPOINT_ENABLED and is_chapter_end and current_scene_count > 0:
            print("\n" + "="*60)
            print(f"📖 CHAPTER {current_chapter} COMPLETE ({current_scene_count} scenes total)")
            print("="*60)
            
            # Show quality metrics
            word_count = compute_current_word_count(manifest, MANUSCRIPT_FILE_DEFAULT)
            target_words = get_target_word_count(manifest)
            progress_pct = (word_count / target_words * 100) if target_words > 0 else 0
            
            print(f"\n📊 Progress: {word_count:,} / {target_words:,} words ({progress_pct:.1f}%)")
            print(f"📄 Manuscript: {manuscript_path}")
            print(f"\n💡 Review the chapter and provide feedback to improve quality.")
            print(f"   Press ENTER to continue, or type 'pause' to stop for detailed review.")
            print(f"   (Auto-continuing in {HUMAN_REVIEW_TIMEOUT // 60} minutes if no response)\n")
            
            try:
                user_input = input_with_timeout("   > ", HUMAN_REVIEW_TIMEOUT)
                
                if user_input is None:
                    # Timeout occurred - generate AI review and continue
                    print("\n   ⏰ No response received. Generating AI review...")
                    ai_review = generate_ai_chapter_review(manuscript_path)
                    print(f"\n   🤖 AUTO-REVIEW:\n   {ai_review}\n")
                    print("   ▶️  Auto-continuing to next chapter...")
                elif user_input.strip().lower() in ('pause', 'stop', 'review', 'p', 's', 'r'):
                    print("\n⏸️  Pausing for human review.")
                    print(f"   Review manuscript at: {manuscript_path}")
                    print("   Make any edits directly, then restart the agent to continue.")
                    print("="*60 + "\n")
                    break  # Exit the main loop for review
                else:
                    print("   ▶️  Continuing to next chapter...")
            except KeyboardInterrupt:
                print("\n⏹️  Interrupted by user. Exiting...")
                break


def main():
    import argparse
    import sys
    import glob
    
    # Parse arguments
    parser = argparse.ArgumentParser(description="Novelist Agent")
    parser.add_argument("--project", type=str, help="Path to project directory")
    args = parser.parse_args()
    
    # Handle project context
    if args.project:
        project_path = os.path.abspath(args.project)
        if os.path.exists(project_path):
            print(f"📂 Switching context to: {project_path}")
            os.chdir(project_path)
            setup_project_paths(project_path)
            if os.path.exists("story.db"):
                print(f"   (Found story.db)")
        else:
            print(f"❌ Project path not found: {project_path}")
            sys.exit(1)
            
    # Auto-Detect / Project Picker
    elif not os.path.exists(MANIFEST_FILE):
        # We are likely in Root without a root story.
        # Check for 'projects' folder
        projects_dir = os.path.abspath("projects")
        available_projects = []
        
        if os.path.exists(projects_dir):
            # Scan for folders with story_manifest.json
            for d in os.listdir(projects_dir):
                full_path = os.path.join(projects_dir, d)
                if os.path.isdir(full_path) and os.path.exists(os.path.join(full_path, "story_manifest.json")):
                    # Get title from manifest? Or just dir name
                    available_projects.append(d)
        
        if available_projects:
            print("\n📚 Available Projects:")
            for i, p in enumerate(available_projects):
                print(f"   [{i+1}] {p}")
            print(f"   [N] Create New (Launch Dashboard)")
            print(f"   [Q] Quit")
            
            choice = input("\nSelect a project to load: ").strip().lower()
            
            if choice == 'n':
                print("🚀 Launching Dashboard for Project Creation...")
                try:
                    subprocess.Popen(["streamlit", "run", "dashboard.py"], shell=True)
                except Exception as e:
                    print(f"Error launching dashboard: {e}")
                sys.exit(0)
            elif choice == 'q':
                sys.exit(0)
            elif choice.isdigit() and 1 <= int(choice) <= len(available_projects):
                selected = available_projects[int(choice)-1]
                target_path = os.path.join(projects_dir, selected)
                print(f"📂 Switching context to: {target_path}")
                os.chdir(target_path)
                setup_project_paths(target_path)
            else:
                print("❌ Invalid selection.")
                sys.exit(1)
        else:
             print(f"⚠️  No Story Manifest found in current folder.")
             print(f"   (No projects found in {projects_dir})")
             print("\n   Run 'streamlit run dashboard.py' to create a New Story.")
             input("   Press Enter to exit...")
             sys.exit(1)

    # START AGENT
    print(f"🤖 Novelist Agent initializing...")
    if not check_ollama_connection():
         print(f"❌ Cannot connect to Ollama at {os.environ.get('OLLAMA_HOST', 'localhost:11434')}")
         print("   Please start Ollama and try again.")
         sys.exit(1)

    print(f"✅ Connected to {LLM_PROVIDER.upper()}")
    print(f"   Writer: {WRITER_MODEL}")
    print(f"   Critic: {CRITIC_MODEL}")
    
    # Manifest loading (now relative to project dir)
    if not os.path.exists(MANIFEST_FILE):
        print(f"⚠️  Manifest not found: {MANIFEST_FILE}")
        sys.exit(1)
        
    manifest = safe_read_json(MANIFEST_FILE, {})
    title = manifest.get("title", "Untitled Story")
    print(f"\n📘 Story: {title}")
    
    # Start loop
    draft_loop(manifest)

if __name__ == "__main__":
    main()
