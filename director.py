"""
director.py — Dual-Engine Director (Protocol 4090)

Orchestrates between two specialized sub-models:
- The Architect (DeepSeek R1): Logic, plotting, outlining, beat sheets
- The Author (L3.2 Rogue): Prose, scenes, dialogue, descriptions

This module parses the story profile and delegates tasks to the appropriate engine.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from config import (
    WRITER_MODEL, CRITIC_MODEL, MODEL_PRESETS,
    ARCHITECT_SYSTEM_PROMPT, ROGUE_SYSTEM_PROMPT,
)
from ollama_client import call_ollama
from file_utils import safe_read_json

# Constants
MANIFEST_FILE = "story_manifest.json"
STATE_FILE = "world_state.json"


# =============================================================================
# STORY PROFILE CONTEXT EXTRACTION
# =============================================================================
def load_story_context() -> Dict[str, Any]:
    """Load story context from manifest and world state files."""
    manifest = safe_read_json(MANIFEST_FILE, {})
    world_state = safe_read_json(STATE_FILE, {})
    
    # Extract key variables
    style = manifest.get("style", {})
    planning = manifest.get("planning", {})
    
    context = {
        "title": manifest.get("title", "Untitled"),
        "synopsis": manifest.get("synopsis", ""),
        "activation_key": style.get("activation_key", "(immersive fiction)"),
        "voice_notes": style.get("voice_notes", []),
        "tone": style.get("tone", ""),
        "pov": style.get("pov", "third_limited"),
        "theme": style.get("theme", ""),
        "structure_blend": planning.get("structure_blend", []),
        "structure_heat": planning.get("structure_heat", 0.25),
        "characters": world_state.get("characters", {}),
        "current_time": world_state.get("current_time", ""),
        "current_location": world_state.get("current_location", ""),
        "weather": world_state.get("weather", ""),
        "inventory": world_state.get("inventory", []),
    }
    
    return context


def format_structure_blend(blend: List[Dict[str, Any]]) -> str:
    """Format structure blend for prompt injection."""
    if not blend:
        return "No specific structure defined"
    return ", ".join([f"{b['style']} ({b['weight']*100:.0f}%)" for b in blend])


def format_voice_notes(notes: List[str]) -> str:
    """Format voice notes for prompt injection."""
    if not notes:
        return "No specific style directives"
    if isinstance(notes, str):
        return notes
    return "\n".join([f"- {note}" for note in notes])


def format_characters(characters: Dict[str, Any]) -> str:
    """Format character bible for prompt injection."""
    if not characters:
        return "No characters defined"
    lines = []
    for name, info in characters.items():
        voice = info.get("voice", "")
        role = info.get("role", "")
        arc = info.get("arc", "")
        lines.append(f"- {name} ({role}): Voice: {voice}. Arc: {arc}")
    return "\n".join(lines)


# =============================================================================
# ROUTINE A: THE ARCHITECT (DeepSeek R1)
# =============================================================================
def delegate_to_architect(
    task: str,
    context: Optional[Dict[str, Any]] = None
) -> Tuple[str, str]:
    """
    Delegate to The Architect for logic, plotting, and structural tasks.
    
    Returns: (thinking_output, final_output)
    """
    if context is None:
        context = load_story_context()
    
    structure = format_structure_blend(context["structure_blend"])
    heat = context["structure_heat"]
    characters = format_characters(context["characters"])
    
    # Construct the sub-prompt
    prompt = f"""You are ARCHITECT_CORE. Activate <think> tags immediately.

CONSTRAINTS:
- Adhere to a plot structure blend of: {structure}
- Structural adherence heat: {heat} (0=Strict, 1=Chaotic)

WORLD STATE:
- Current Time: {context['current_time']}
- Current Location: {context['current_location']}
- Weather: {context['weather']}
- Inventory: {context['inventory']}

CAST BIBLE:
{characters}

TASK:
{task}

PROTOCOL:
1. Use <think> tags to deconstruct the request
2. Simulate 3 approaches inside <think>
3. Red-team your own solutions
4. Select optimal path after verification
5. Output ONLY the final plan/structure after </think>
"""
    
    response = call_ollama([
        {"role": "system", "content": ARCHITECT_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ], model=WRITER_MODEL)  # DeepSeek R1
    
    # Parse thinking and output
    thinking = ""
    final = response or ""
    
    think_match = re.search(r'<think>(.*?)</think>', response or "", re.DOTALL)
    if think_match:
        thinking = think_match.group(1).strip()
        final = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
    
    return thinking, final


# =============================================================================
# ROUTINE B: THE AUTHOR (L3.2 Rogue)
# =============================================================================
def delegate_to_author(
    task: str,
    beat_sheet: str = "",
    context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Delegate to The Author for prose, scenes, and creative writing.
    
    Args:
        task: The writing task description
        beat_sheet: Optional beat sheet from The Architect
        context: Story context (loaded if not provided)
    
    Returns: Generated prose
    """
    if context is None:
        context = load_story_context()
    
    activation_key = context["activation_key"]
    voice_notes = format_voice_notes(context["voice_notes"])
    characters = format_characters(context["characters"])
    
    # Construct the sub-prompt with exact headers
    prompt = f"""!!! SYSTEM OVERRIDE: BRAINSTORM_40X_ACTIVE !!!

[ACTIVATION_KEY]: {activation_key}

[MASTERSTORY]: NarrStrct(StryPlnng,Strbd,ScnSttng,Exps,Dlg,Pc)-CharDvlp(ChrctrCrt,ChrctrArcs,Mtvtn,Bckstry,Rltnshps,Dlg*)-PltDvlp(StryArcs,PltTwsts,Sspns,Fshdwng,Climx,Rsltn)-ConfResl(Antg,Obstcls,Rsltns,Cnsqncs,Thms,Symblsm)-EmotImpct(Empt,Tn,Md,Atmsphr,Imgry,Symblsm)-Delvry(Prfrmnc,VcActng,PblcSpkng,StgPrsnc,AudncEngmnt,Imprv)

[*DialogWrt]:(1a-CharDvlp-1a.1-Backgrnd-1a.2-Personality-1a.3-GoalMotiv)>2(2a-StoryStruc-2a.1-PlotPnt-2a.2-Conflict-2a.3-Resolution)>3(3a-DialogTech-3a.1-ShowDontTell-3a.2-Subtext-3a.3-VoiceTone-3a.4-Pacing-3a.5-VisualDescrip)>4(4a-DialogEdit-4a.1-ReadAloud-4a.2-Feedback-4a.3-Revision)

WORLD STATE:
- Time: {context['current_time']}
- Location: {context['current_location']}
- Weather: {context['weather']}
- Inventory: {context['inventory']}

CAST BIBLE:
{characters}

STYLE DIRECTIVES:
{voice_notes}

{"BEAT SHEET:" + chr(10) + beat_sheet if beat_sheet else ""}

TASK:
{task}

REQUIREMENTS:
- Engage at least 3 senses (Sight, Sound, Smell, Touch, Taste)
- Do NOT summarize; SIMULATE
- Micro-focus: dirt under fingernails, flicker of light, micro-expressions
- Dense, literary prose with varied cadence

CURRENT MODE: [High-Contrast / Visceral / Immersive]
BEGIN SCENE:
"""
    
    response = call_ollama([
        {"role": "system", "content": ROGUE_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ], model=CRITIC_MODEL)  # L3.2 Rogue
    
    return response or ""


# =============================================================================
# TASK CLASSIFICATION
# =============================================================================
def classify_task(task: str) -> str:
    """
    Classify whether a task should go to Architect or Author.
    
    Returns: "architect" or "author"
    """
    architect_keywords = [
        "outline", "plot", "beat", "structure", "logic", "timeline",
        "plan", "diagram", "schema", "architecture", "breakdown",
        "analyze", "verify", "check", "consistency", "causality"
    ]
    
    author_keywords = [
        "write", "scene", "prose", "dialogue", "describe", "narrate",
        "rewrite", "expand", "render", "generate", "draft", "story"
    ]
    
    task_lower = task.lower()
    
    architect_score = sum(1 for kw in architect_keywords if kw in task_lower)
    author_score = sum(1 for kw in author_keywords if kw in task_lower)
    
    if architect_score > author_score:
        return "architect"
    elif author_score > architect_score:
        return "author"
    else:
        # Default to author for ambiguous tasks
        return "author"


# =============================================================================
# MAIN DIRECTOR INTERFACE
# =============================================================================
def direct(task: str, engine: Optional[str] = None) -> Dict[str, Any]:
    """
    Main director interface. Delegates task to appropriate engine.
    
    Args:
        task: The task to execute
        engine: Force specific engine ("architect" or "author"), or auto-classify
    
    Returns: Dict with engine, thinking (if Architect), and output
    """
    context = load_story_context()
    
    if engine is None:
        engine = classify_task(task)
    
    result = {
        "engine": engine,
        "task": task,
        "thinking": "",
        "output": "",
        "context": {
            "time": context["current_time"],
            "location": context["current_location"],
        }
    }
    
    if engine == "architect":
        thinking, output = delegate_to_architect(task, context)
        result["thinking"] = thinking
        result["output"] = output
    else:
        output = delegate_to_author(task, context=context)
        result["output"] = output
    
    return result


def bridge_workflow(plot_task: str, prose_task: str) -> Dict[str, Any]:
    """
    Execute the "Bridge" two-step workflow:
    1. Send plotting task to Architect
    2. Send prose task to Author with Architect's output as beat sheet
    
    Returns: Dict with both outputs
    """
    context = load_story_context()
    
    # Step 1: Architect creates the blueprint
    thinking, blueprint = delegate_to_architect(plot_task, context)
    
    # Step 2: Author renders the prose using the blueprint
    prose = delegate_to_author(prose_task, beat_sheet=blueprint, context=context)
    
    return {
        "architect": {
            "thinking": thinking,
            "blueprint": blueprint
        },
        "author": {
            "prose": prose
        }
    }
