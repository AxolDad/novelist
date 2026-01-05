"""
story_architect.py — Story Architecture & Reasoning Engine

High-level story reasoning for DeepSeek-R1:
- Arc generation with Chain-of-Thought reasoning
- Context compression into Memory Anchors
- Style Bible generation and management
- Plot progression validation
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from config import WRITER_MODEL, CRITIC_MODEL
from ollama_client import call_ollama, extract_clean_json
from file_utils import safe_read_json, safe_write_json, tail_excerpt


# =============================================================================
# ARC REASONING
# =============================================================================

def generate_story_arc(
    manifest: Dict[str, Any],
    world_state: Dict[str, Any],
    arc_ledger: Dict[str, Any],
    target_scenes: int = 10
) -> Dict[str, Any]:
    """
    Use R1's reasoning to generate a complete story arc with causal chain.
    Works backward from possible endings to create inevitable progression.
    """
    title = manifest.get("title", "(untitled)")
    synopsis = manifest.get("synopsis", "") or manifest.get("description", "")
    style = manifest.get("style", {}) or {}
    theme = style.get("theme", "")
    tone = style.get("tone", "")
    
    # Get character context
    characters = world_state.get("characters", {})
    char_descriptions = []
    for name, info in characters.items():
        status = info.get("status", "unknown")
        char_descriptions.append(f"- {name}: {status}")
    char_block = "\n".join(char_descriptions) if char_descriptions else "- To be developed through the narrative"
    
    # Current story state from arc ledger
    existing_stakes = arc_ledger.get("stakes", [])
    existing_questions = arc_ledger.get("unresolved_questions", [])
    scene_history = arc_ledger.get("scene_history", [])
    
    prompt = f"""You are a story architect. Your task is to reason through a complete narrative arc.

<premise>
Title: {title}
Synopsis: {synopsis}
Theme: {theme}
Tone: {tone}

Characters:
{char_block}

Existing Stakes: {json.dumps(existing_stakes) if existing_stakes else "None yet"}
Unresolved Questions: {json.dumps(existing_questions) if existing_questions else "None yet"}
Scenes Written So Far: {len(scene_history)}
</premise>

<think>
Reason through the following steps:

1. CORE TENSION: What is the fundamental conflict or question at the heart of this premise?

2. POSSIBLE ENDPOINTS: Generate 3 distinct ways this story could end:
   - TRIUMPH: The protagonist overcomes and is transformed
   - TRAGEDY: The protagonist fails or pays an irreversible price  
   - AMBIGUITY: The situation resolves but the meaning is uncertain

3. CHOOSE: Select the most compelling endpoint. Justify why it creates the strongest emotional impact.

4. MIDPOINT REVERSAL: What event at the story's center makes the chosen ending feel inevitable?

5. INCITING INCIDENT: What moment starts the chain of events? (This may already exist if scenes are written)

6. CAUSAL CHAIN: Work backward from ending to midpoint to beginning. Each scene must CAUSE the next.
</think>

Now output a structured arc with exactly {target_scenes} scenes.

Return JSON ONLY:
{{
  "core_tension": "The fundamental conflict in one sentence",
  "chosen_endpoint": "triumph" | "tragedy" | "ambiguity",
  "endpoint_description": "What specifically happens at the end",
  "midpoint_reversal": "The turning point event",
  "scenes": [
    {{
      "index": 1,
      "title": "Scene Title",
      "beat": "inciting_incident" | "rising_action" | "midpoint" | "falling_action" | "climax" | "resolution",
      "before_state": "Character's situation at scene START",
      "after_state": "Character's situation at scene END (must be DIFFERENT)",
      "goal": "What must happen in this scene",
      "irreversible_change": "What cannot be undone after this scene"
    }}
  ]
}}
"""
    
    print("   🧠 R1 reasoning through story arc...")
    out = call_ollama([{"role": "user", "content": prompt}], model=WRITER_MODEL, json_mode=True)
    data = extract_clean_json(out)
    
    if not data or not isinstance(data.get("scenes"), list) or len(data["scenes"]) == 0:
        print("   ⚠️ Arc generation failed. Creating minimal structure...")
        # Fallback with basic three-act structure
        data = {
            "core_tension": "Survival against the elements and inner demons",
            "chosen_endpoint": "ambiguity",
            "endpoint_description": "The protagonist makes a choice, but the outcome is left uncertain",
            "midpoint_reversal": "A discovery that changes the protagonist's understanding",
            "scenes": [
                {
                    "index": i + 1,
                    "title": f"Scene {i + 1}",
                    "beat": ["inciting_incident", "rising_action", "rising_action", "midpoint", 
                            "rising_action", "falling_action", "falling_action", "climax", 
                            "resolution", "resolution"][i % 10],
                    "before_state": "Protagonist faces their situation",
                    "after_state": "Situation has escalated or shifted",
                    "goal": f"Advance the narrative - scene {i + 1}",
                    "irreversible_change": "A choice made or information revealed"
                }
                for i in range(target_scenes)
            ]
        }
    
    print(f"   ✅ Generated arc: {data.get('chosen_endpoint', 'unknown')} ending with {len(data.get('scenes', []))} scenes")
    return data


# =============================================================================
# CONTEXT COMPRESSION
# =============================================================================

def build_memory_anchor(
    world_state: Dict[str, Any],
    arc_ledger: Dict[str, Any],
    recent_prose: str,
    current_scene_index: int,
    manuscript_summary: str = ""
) -> Dict[str, Any]:
    """
    Compress full story state into a hierarchical Memory Anchor.
    
    ARCHITECTURE FIX #3: Hierarchical Context Compression
    - Layer 1: Full manuscript summary (~200 words)
    - Layer 2: Current chapter context (all scenes in chapter)
    - Layer 3: Immediate context (last 2-3 scenes verbatim excerpts)
    """
    # Extract only active plot threads - EXPANDED from 5 to 10
    unresolved = arc_ledger.get("unresolved_questions", [])[-10:]
    stakes = arc_ledger.get("stakes", [])[-5:]  # Expanded from 3
    
    # Get current character states (compressed)
    char_states = []
    for name, info in (world_state.get("characters") or {}).items():
        status = info.get("status", "")
        location = info.get("location", "")
        char_states.append(f"{name}: {status}" + (f" @ {location}" if location else ""))
    
    # LAYER 2: Chapter context - group scenes by chapter (every 5 scenes)
    scene_history = arc_ledger.get("scene_history", [])
    chapter_size = 5
    current_chapter = (current_scene_index - 1) // chapter_size
    chapter_start = current_chapter * chapter_size
    chapter_scenes = scene_history[chapter_start:chapter_start + chapter_size]
    
    # Build chapter summary
    chapter_context = []
    for sh in chapter_scenes:
        title = sh.get("title", "Scene")
        consequence = sh.get("consequence", "")
        chapter_context.append(f"• {title}: {consequence}")
    
    # Get narrative delta from recent scenes (LAYER 3)
    last_scenes = scene_history[-3:] if scene_history else []
    last_scene = scene_history[-1] if scene_history else {}
    last_consequence = last_scene.get("consequence", "Story just beginning")
    last_turn = last_scene.get("turn", "")
    
    # Build recent scenes summary (immediate context)
    recent_context = []
    for sh in last_scenes:
        recent_context.append({
            "title": sh.get("title", ""),
            "turn": sh.get("turn", ""),
            "consequence": sh.get("consequence", "")
        })
    
    anchor = {
        "scene_number": current_scene_index,
        "total_scenes": len(scene_history),
        
        # LAYER 1: Manuscript summary (if available)
        "manuscript_summary": manuscript_summary[:500] if manuscript_summary else "",
        
        # LAYER 2: Current chapter context
        "current_chapter": current_chapter + 1,
        "chapter_context": chapter_context,
        
        # LAYER 3: Immediate context
        "recent_scenes": recent_context,
        "last_scene": {
            "title": last_scene.get("title", "Opening"),
            "turn": last_turn,
            "consequence": last_consequence,
            "new_pressure": last_scene.get("new_pressure", "")
        },
        
        # Story state
        "plot_threads": unresolved,
        "active_stakes": stakes,
        "character_states": char_states,
        "world_time": world_state.get("current_time", ""),
        "world_location": world_state.get("current_location", ""),
        "inventory": world_state.get("inventory", [])[-5:]
    }
    
    return anchor


def compress_for_prompt(anchor: Dict[str, Any]) -> str:
    """Convert hierarchical Memory Anchor to a structured prompt section."""
    lines = [
        f"[Scene {anchor.get('scene_number', '?')} of {anchor.get('total_scenes', '?')} | Chapter {anchor.get('current_chapter', '?')}]",
        f"Time/Place: {anchor.get('world_time', '?')} | {anchor.get('world_location', '?')}",
        ""
    ]
    
    # LAYER 1: Manuscript summary (if available)
    if anchor.get("manuscript_summary"):
        lines.append("═══ STORY SO FAR ═══")
        lines.append(anchor["manuscript_summary"])
        lines.append("")
    
    # LAYER 2: Chapter context
    if anchor.get("chapter_context"):
        lines.append(f"═══ CHAPTER {anchor.get('current_chapter', '?')} SCENES ═══")
        for ctx in anchor["chapter_context"]:
            lines.append(ctx)
        lines.append("")
    
    # LAYER 3: Immediate context (recent scenes)
    if anchor.get("recent_scenes"):
        lines.append("═══ LAST 3 SCENES ═══")
        for rs in anchor["recent_scenes"]:
            if rs.get("title"):
                lines.append(f"• {rs['title']}: {rs.get('consequence', '')}")
        lines.append("")
    
    # Characters
    lines.append("Characters:")
    for cs in anchor.get("character_states", []):
        lines.append(f"  • {cs}")
    
    # Last scene detail
    lines.append("")
    lines.append("Most Recent Scene:")
    last = anchor.get("last_scene", {})
    lines.append(f"  • {last.get('title', 'N/A')}: {last.get('consequence', 'N/A')}")
    if last.get("new_pressure"):
        lines.append(f"  • New Pressure: {last.get('new_pressure')}")
    
    # Plot threads (expanded)
    if anchor.get("plot_threads"):
        lines.append("")
        lines.append("Open Threads:")
        for pt in anchor["plot_threads"]:
            # Handle both string and dict formats
            if isinstance(pt, dict):
                pt = pt.get("name", str(pt))
            lines.append(f"  • {pt}")
    
    # Stakes
    if anchor.get("active_stakes"):
        lines.append("")
        lines.append("Stakes:")
        for s in anchor["active_stakes"]:
            if isinstance(s, dict):
                s = s.get("name", str(s))
            lines.append(f"  • {s}")
    
    return "\n".join(lines)


# =============================================================================
# STYLE BIBLE
# =============================================================================

STYLE_BIBLE_FILE = "meta/style_bible.json"

def generate_style_bible(manifest: Dict[str, Any], sample_prose: str = "") -> Dict[str, Any]:
    """
    Generate or update the Style Bible based on manifest and sample prose.
    This creates consistent voice/tone rules for the entire story.
    """
    style = manifest.get("style", {}) or {}
    
    # If we have sample prose, analyze it
    if sample_prose and len(sample_prose) > 500:
        prompt = f"""Analyze this prose sample and extract consistent style rules.

<sample>
{sample_prose[:2000]}
</sample>

Return JSON with these fields:
{{
  "tone": ["keyword1", "keyword2", "keyword3"],
  "pov": "first_person" | "third_limited" | "third_omniscient",
  "sentence_style": "description of typical sentence structure",
  "sensory_focus": "which senses are emphasized",
  "dialogue_style": "how characters speak",
  "pacing": "description of narrative rhythm",
  "forbidden": ["things to avoid", "patterns that break voice"],
  "signature_moves": ["distinctive techniques used"]
}}
"""
        out = call_ollama([{"role": "user", "content": prompt}], model=CRITIC_MODEL, json_mode=True)
        data = extract_clean_json(out)
        if data:
            return data
    
    # Default style bible from manifest
    return {
        "tone": [style.get("tone", "literary"), "introspective", "grounded"],
        "pov": style.get("pov", "third_limited"),
        "sentence_style": "Varied rhythm. Short sentences for tension, longer for atmosphere.",
        "sensory_focus": "Sound and texture over pure visual description",
        "dialogue_style": "Subtext-heavy. Characters don't say what they mean directly.",
        "pacing": "Slow build with sharp, unexpected turns",
        "forbidden": [
            "adverbs in dialogue tags",
            "naming emotions directly (no 'he felt sad')",
            "passive voice in action",
            "filter words (he saw, she noticed, he felt)"
        ],
        "signature_moves": [
            "Physical details reveal emotional states",
            "Silence and absence carry meaning",
            "Environment reflects internal state"
        ]
    }


def load_style_bible() -> Dict[str, Any]:
    """Load the Style Bible from disk."""
    return safe_read_json(STYLE_BIBLE_FILE, {})


def save_style_bible(bible: Dict[str, Any]) -> None:
    """Save the Style Bible to disk."""
    safe_write_json(STYLE_BIBLE_FILE, bible)


def style_bible_to_prompt(bible: Dict[str, Any]) -> str:
    """Convert Style Bible to a compact prompt section."""
    if not bible:
        return ""
    
    lines = ["[STYLE BIBLE]"]
    
    if bible.get("tone"):
        lines.append(f"Tone: {', '.join(bible['tone'])}")
    if bible.get("pov"):
        lines.append(f"POV: {bible['pov']}")
    if bible.get("sensory_focus"):
        lines.append(f"Sensory Focus: {bible['sensory_focus']}")
    if bible.get("forbidden"):
        lines.append(f"FORBIDDEN: {'; '.join(bible['forbidden'][:4])}")
    
    return "\n".join(lines)


# =============================================================================
# PROGRESSION VALIDATION
# =============================================================================

def validate_progression(
    before_state: str,
    after_state: str,
    scene_text: str,
    previous_scenes: List[str]
) -> Dict[str, Any]:
    """
    Validate that a scene actually advances the plot.
    Returns pass/fail with reasoning.
    """
    # Check for repetition against previous scenes
    repetition_sample = "\n---\n".join(previous_scenes[-3:]) if previous_scenes else ""
    
    prompt = f"""You are a story progression validator. Analyze whether this scene advances the plot.

<before_state>
{before_state}
</before_state>

<after_state>
{after_state}
</after_state>

<scene_excerpt>
{tail_excerpt(scene_text, 1500)}
</scene_excerpt>

<previous_scenes_sample>
{repetition_sample[:1000] if repetition_sample else "No previous scenes"}
</previous_scenes_sample>

<think>
1. What was the character's situation at scene START?
2. What is the character's situation at scene END?
3. Is the change IRREVERSIBLE? (If they can just go back, it's not real progression)
4. Does this change create NEW problems or resolve OLD ones?
5. Is this scene largely repeating content from previous scenes?
</think>

Return JSON:
{{
  "verdict": "PASS" | "WARN" | "FAIL",
  "change_detected": true | false,
  "irreversible": true | false,
  "repetition_detected": true | false,
  "reasoning": "Brief explanation",
  "fix_suggestion": "If FAIL or WARN, what should change"
}}
"""
    
    out = call_ollama([{"role": "user", "content": prompt}], model=CRITIC_MODEL, json_mode=True)
    data = extract_clean_json(out)
    
    if not data:
        return {
            "verdict": "WARN",
            "change_detected": True,
            "irreversible": False,
            "repetition_detected": False,
            "reasoning": "Could not validate - proceeding with caution",
            "fix_suggestion": ""
        }
    
    return data


def extract_scene_delta(scene_text: str, world_state: Dict[str, Any]) -> str:
    """
    Extract what changed in this scene as a one-line summary.
    Used for Memory Anchor updates.
    """
    prompt = f"""Summarize what CHANGED in this scene in exactly one sentence.
Focus on irreversible actions, revelations, or decisions.

<scene>
{tail_excerpt(scene_text, 1200)}
</scene>

<current_world_state>
Location: {world_state.get('current_location', 'unknown')}
Time: {world_state.get('current_time', 'unknown')}
</current_world_state>

Return JSON:
{{
  "delta": "One sentence describing what changed",
  "new_tension": "One sentence describing any new conflict or question raised"
}}
"""
    
    out = call_ollama([{"role": "user", "content": prompt}], model=CRITIC_MODEL, json_mode=True)
    data = extract_clean_json(out)
    
    if data:
        return data.get("delta", "Scene completed")
    return "Scene completed"
