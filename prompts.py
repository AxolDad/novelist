"""
prompts.py — System Prompts and Prompt Builders

Contains all system prompts and functions for building structured prompts:
- Critic system prompt
- Writer frame prompt
- Structure guidance builder
- Micro-outline builder
"""

import json
from typing import Any, Dict, List, Optional

from config import WRITER_MODEL, STYLES_MASTER_FILE
from file_utils import safe_read_json, safe_write_json
from ollama_client import call_ollama, extract_clean_json
from prompt_loader import load_prompt
from logger import logger


# ------------------------------------------------------------------
#  SYSTEM PROMPTS
# ------------------------------------------------------------------

# Three specialized critics for comprehensive review
# ------------------------------------------------------------------
#  SPECIALIZED CRITIC PROMPTS (Parallel Tribunal)
# ------------------------------------------------------------------

PROSE_CRITIC_PROMPT = load_prompt("critics", "prose.md")
REDUNDANCY_CRITIC_PROMPT = load_prompt("critics", "redundancy.md")
ARC_CRITIC_PROMPT = load_prompt("critics", "arc.md")
ARC_CRITIC_EARLY_PROMPT = load_prompt("critics", "arc_early.md")


# ------------------------------------------------------------------
#  PARALLEL TRIBUNAL ENGINE
# ------------------------------------------------------------------

def critique_scene(text: str, story_context: Optional[str] = None, scene_count: int = 0) -> Dict[str, Any]:
    """
    Runs the 3-Reviewer Tribunal in PARALLEL.
    Aggregates results from Prose, Redundancy, and Arc critics.
    
    Args:
        text: The scene text to critique
        story_context: Previous scene summaries for continuity checking
        scene_count: Number of scenes written so far (0 = first scene)
    """
    from config import CRITIC_MODEL
    import concurrent.futures
    
    # 1. Define the 3 tasks
    def run_prose():
        out = call_ollama([
            {"role": "system", "content": PROSE_CRITIC_PROMPT},
            {"role": "user", "content": f"SCENE:\n{text}"}
        ], model=CRITIC_MODEL, json_mode=True)
        data = extract_clean_json(out)
        if not data:
            logger.error(f"Prose Critic JSON Failed. Raw Output:\n{out}")
            return {"prose_score": 50, "prose_fix": "Prose review failed."}
        return data

    def run_redundancy():
        out = call_ollama([
            {"role": "system", "content": REDUNDANCY_CRITIC_PROMPT},
            {"role": "user", "content": f"SCENE:\n{text}"}
        ], model=CRITIC_MODEL, json_mode=True)
        data = extract_clean_json(out)
        if not data:
            logger.error(f"Redundancy Critic JSON Failed. Raw Output:\n{out}")
            return {"redundancy_score": 50, "redundancy_fix": "Redundancy review failed."}
        return data

    def run_arc():
        # Early-story behavior: Skip for first 2 scenes, modified prompt for scenes 3-5
        if scene_count < 2:
            # First 2 scenes: Skip Arc Critic entirely, return passing score
            return {
                "arc_score": 95,  # Passing score (avoids triggering rewrites)
                "arc_fix": "Arc review skipped (early story - no continuity context yet).",
                "irreversible_change": "N/A (early story)"
            }
        elif scene_count < 5:
            # Scenes 3-5: Use early-story prompt focused on stakes rather than continuity
            arc_prompt = ARC_CRITIC_EARLY_PROMPT
        else:
            # Scene 6+: Full Arc Critic with continuity checks
            arc_prompt = ARC_CRITIC_PROMPT
            
        context_block = f"STORY CONTEXT:\n{story_context}\n\n" if story_context else ""
        out = call_ollama([
            {"role": "system", "content": arc_prompt},
            {"role": "user", "content": f"{context_block}SCENE:\n{text}"}
        ], model=CRITIC_MODEL, json_mode=True)
        data = extract_clean_json(out)
        if not data:
            logger.error(f"Arc Critic JSON Failed. Raw Output:\n{out}")
            return {"arc_score": 50, "arc_fix": "Arc review failed.", "irreversible_change": "UNKNOWN"}
        return data

    # 2. Execute in parallel
    arc_mode = "Skipped" if scene_count < 2 else ("Stakes" if scene_count < 5 else "Full")
    logger.info(f"Summoning Parallel Tribunal (3 Agents)... [Arc: {arc_mode}]")
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_prose = executor.submit(run_prose)
        future_redundancy = executor.submit(run_redundancy)
        future_arc = executor.submit(run_arc)
        
        # Wait for all
        results.update(future_prose.result())
        results.update(future_redundancy.result())
        results.update(future_arc.result())
        
    # 3. Aggregate & Calculate Priority
    # Determine which score is lowest to set 'priority_fix'
    scores = {
        "prose": results.get("prose_score", 0),
        "redundancy": results.get("redundancy_score", 0),
        "arc": results.get("arc_score", 0)
    }
    lowest_category = min(scores, key=scores.get)
    
    # Map lowest category to its fix
    fix_map = {
        "prose": results.get("prose_fix", ""),
        "redundancy": results.get("redundancy_fix", ""),
        "arc": results.get("arc_fix", "")
    }
    results["priority_fix"] = f"[{lowest_category.upper()} PRIORITY]: {fix_map[lowest_category]}"
    
    return results


# ------------------------------------------------------------------
#  DRAFT SELECTOR (Editor-in-Chief)
# ------------------------------------------------------------------

SELECTOR_PROMPT = load_prompt("critics", "selector.md")

def select_best_draft(drafts: List[str]) -> Dict[str, Any]:
    """
    Asks the Critic Model to pick the best of 3 drafts.
    Returns JSON with 'best_draft_index' (1-based) and 'reasoning'.
    """
    from config import CRITIC_MODEL
    
    if len(drafts) < 2:
        return {"best_draft_index": 1, "reasoning": "Only one draft provided."}
        
    formatted_drafts = ""
    for i, d in enumerate(drafts):
        formatted_drafts += f"\n[DRAFT {i+1}]\n{d[:3000]}...\n(truncated for evaluation)\n"

    prompt = f"""
{SELECTOR_PROMPT}

CANDIDATE DRAFTS:
{formatted_drafts}
"""

    out = call_ollama([{"role": "user", "content": prompt}], model=CRITIC_MODEL, json_mode=True)
    return extract_clean_json(out) or {"best_draft_index": 1, "reasoning": "Selection failed."}


WRITER_FRAME_PROMPT = load_prompt("system", "writer_frame.md")


# ------------------------------------------------------------------
#  STYLES MASTER
# ------------------------------------------------------------------
def load_styles_master() -> Dict[str, Any]:
    """
    Structural guidance library.
    Create/extend styles_master.json to teach the system new structures.
    """
    default_master = {
        "version": "1.0.0",
        "styles": {
            "heros_journey": {
                "label": "Hero's Journey",
                "beats": [
                    "Ordinary World", "Call to Adventure", "Refusal of the Call", "Meeting the Mentor",
                    "Crossing the Threshold", "Tests/Allies/Enemies", "Approach to the Inmost Cave",
                    "Ordeal", "Reward", "The Road Back", "Resurrection", "Return with the Elixir"
                ],
                "notes": "Transformational arc; escalating trials; return changed."
            },
            "tragic_plot_embryo": {
                "label": "Tragic Plot Embryo",
                "beats": [
                    "Want", "Unfamiliar situation", "Adaptation", "Fatal flaw blocks transformation",
                    "Failure to return whole", "Earned unhappy ending"
                ],
                "notes": "Tragedy is earned when the flaw prevents integration."
            },
            "take_off_your_pants": {
                "label": "Take Off Your Pants (Hawker)",
                "beats": [
                    "Hook", "Normal world / flaw", "Inciting incident", "Doorway of No Return (Act 1)",
                    "Pinch 1", "Midpoint shift", "Pinch 2", "Darkest moment", "Climax", "Resolution"
                ],
                "notes": "Strong cause-effect; doorways; escalating pressure; flaw-driven choices."
            }
        }
    }
    return safe_read_json(STYLES_MASTER_FILE, default_master)


def build_structure_guidance(manifest: Dict[str, Any]) -> str:
    """
    Builds a compact guidance block for the writer model from weighted structure blends.
    """
    planning = manifest.get("planning", {}) or {}
    blend = planning.get("structure_blend") or []
    heat = float(planning.get("structure_heat", 0.25))  # 0 rigid → 1 autonomous
    master = load_styles_master()
    styles = master.get("styles", {}) or {}

    if not blend:
        # fallback if user hasn't chosen a blend
        blend = [{"style": "take_off_your_pants", "weight": 0.6}, {"style": "heros_journey", "weight": 0.4}]

    lines = []
    lines.append("STRUCTURAL GUIDANCE (Weighted Blend)")
    lines.append(f"- heat: {heat}  (0 = strict adherence, 1 = high autonomy)")
    for item in blend:
        name = (item.get("style") or "").lower().strip()
        if not name:
            continue
        w = float(item.get("weight", 0) or 0)
        s = styles.get(name, {})
        label = s.get("label", name)
        beats = s.get("beats", [])
        notes = s.get("notes", "")
        lines.append(f"- {label} [{int(w*100)}%] beats: {beats}")
        if notes:
            lines.append(f"  notes: {notes}")
    lines.append("Rule: distribute these beats across the whole story in proportion to weights. Deviate only when it increases clarity, momentum, and emotional truth (respect heat).")
    return "\n".join(lines)


# ------------------------------------------------------------------
#  MICRO-OUTLINE BUILDER
# ------------------------------------------------------------------
def build_micro_outline(
    scene_goal: str, 
    arc_ledger: Dict[str, Any], 
    char_bible: Dict[str, Any], 
    world_state: Dict[str, Any],
    scene_arc_info: Optional[Dict[str, Any]] = None,
    previous_scene_summaries: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Build a micro-outline (beat sheet) for the next scene.
    Now requires concrete BEFORE/AFTER states and checks for repetition.
    Includes FIX #5 (expanded context) and FIX #6 (scene diversity).
    """
    # FIX #5: Get MORE scene history (6 instead of 3) for better context
    scene_history = arc_ledger.get("scene_history", [])
    recent_scenes = scene_history[-6:]  # Last 6 for anti-repetition
    all_scenes = scene_history  # Full history for summary
    
    recent_summaries = []
    for sh in recent_scenes:
        recent_summaries.append(f"- {sh.get('title', 'Scene')}: {sh.get('consequence', 'unknown')}")
    anti_repetition_block = "\n".join(recent_summaries) if recent_summaries else "No previous scenes"
    
    # FIX #5: Build compressed ALL SCENES summary for context
    all_scenes_summary = []
    for i, sh in enumerate(all_scenes):
        all_scenes_summary.append(f"Scene {i+1}: {sh.get('title', 'Unknown')} → {sh.get('consequence', 'unknown')}")
    all_scenes_block = "\n".join(all_scenes_summary[-10:]) if all_scenes_summary else "First scene"
    
    # Use scene arc info if provided (from story architect)
    before_state = ""
    after_state = ""
    if scene_arc_info:
        before_state = scene_arc_info.get("before_state", "")
        after_state = scene_arc_info.get("after_state", "")
    
    # Get character names for context
    char_names = list((world_state.get("characters") or {}).keys())
    current_loc = world_state.get("current_location", "unknown")
    current_time = world_state.get("current_time", "unknown")
    
    prompt_template = load_prompt("templates", "micro_outline.md")
    
    # Fill the template
    prompt = prompt_template.format(
        scene_goal=scene_goal,
        before_state_text=before_state if before_state else f"Location: {current_loc}, Time: {current_time}",
        after_state_text=after_state if after_state else "Must be determined - something irreversible happens",
        character_names=', '.join(char_names) if char_names else 'To be shown through action',
        all_scenes_block=all_scenes_block,
        anti_repetition_block=anti_repetition_block,
        current_stakes=json.dumps(arc_ledger.get('stakes', [])[-3:], indent=2),
        unresolved_tensions=json.dumps(arc_ledger.get('unresolved_questions', [])[-3:], indent=2)
    )
    out = call_ollama([{"role": "user", "content": prompt}], model=WRITER_MODEL, json_mode=True)
    data = extract_clean_json(out)
    if data:
        return data
    # fail-safe outline with progression built in
    return {
        "before_state": f"Character at {current_loc}, facing their situation",
        "after_state": "Situation has fundamentally shifted - no going back",
        "irreversible_change": "A decision made or truth revealed that changes everything",
        "want": scene_goal or "Advance toward resolution",
        "obstacle": "An unexpected complication emerges",
        "turn": "New information forces a choice",
        "consequence": "The choice carries a cost that cannot be undone",
        "beats": [
            "Ground the scene in a sharp sensory detail",
            "The obstacle appears and creates friction", 
            "The turn forces action",
            "The consequence changes the situation permanently"
        ],
        "subtext_hook": "What the character avoids saying reveals more than speech",
        "anti_repetition_note": "Focus on plot progression, not atmospheric repetition"
    }




