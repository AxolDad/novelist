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


# ------------------------------------------------------------------
#  SYSTEM PROMPTS
# ------------------------------------------------------------------

# Three specialized critics for comprehensive review
# ------------------------------------------------------------------
#  SPECIALIZED CRITIC PROMPTS (Parallel Tribunal)
# ------------------------------------------------------------------

PROSE_CRITIC_PROMPT = """
ROLE: You are the PROSE CRITIC. Your sole focus is sensory immersion and voice depth.
IGNORE plot logic. IGNORE typos. Focus on the FEEL of the writing.

CRITERIA:
1. SENSORY: Are at least 3 senses engaged (sight, sound, smell, touch, taste)?
2. SPECIFICITY: "cold" vs "forty-degree water stinging his fingers".
3. METAPHOR: Are there vivid or unexpected comparisons?
4. VOICE: Does the narrative distance match the character's state?

OUTPUT FORMAT (JSON ONLY):
{
  "prose_score": <int 0-100>,
  "prose_fix": "ONE specific, actionable fix regarding sensory detail or voice. Example: 'Line 3: Replace \"he felt cold\" with \"ice needles pricked his fingers\"'"
}
"""

REDUNDANCY_CRITIC_PROMPT = """
ROLE: You are the REDUNDANCY CRITIC. You are a ruthless editor.
Your goal is to ELIMINATE weak writing patterns.

DETECT AND FLAG:
1. Filter words: "he saw," "she felt," "he noticed," "she realized," "he thought"
2. Clichés: "heart pounded," "breath caught," "time stood still," "dead silence"
3. Redundant phrasing: "He stood up on his feet" (where else would he stand?)
4.  adverb abuse: "shouted loudly"

SCORING RUBRIC (Strict):
- 95-100: Zero issues.
- 90-94:  1 minor issue.
- 80-89:  2-3 issues.
- <80:    Significant problems.

OUTPUT FORMAT (JSON ONLY):
{
  "redundancy_score": <int 0-100>,
  "redundancy_fix": "Quote the EXACT cliché/filter word and its line, provide rewrite. Example: 'Line 7: \"His heart pounded\" → Show behavior: \"His fist whitened on the rail\"'"
}
"""

ARC_CRITIC_PROMPT = """
ROLE: You are the ARC CRITIC. Your focus is narrative continuity and consequence.
IGNORE prose style. Focus on LOGIC and CAUSALITY.

CRITERIA:
1. CONTINUITY: Does this scene follow logically from the provided summary?
2. CONSISTENCY: Are character motivations/states consistent?
3. PROGRESSION: What IRREVERSIBLE change happens? If nothing changes, the scene fails.

OUTPUT FORMAT (JSON ONLY):
{
  "arc_score": <int 0-100>,
  "arc_fix": "Describe narrative gap or lack of consequence. Example: 'Scene ends where it started. Add a decision that cannot be unmade.'",
  "irreversible_change": "Briefly state the permanent change. If none, write 'NONE'."
}
"""


# ------------------------------------------------------------------
#  PARALLEL TRIBUNAL ENGINE
# ------------------------------------------------------------------

def critique_scene(text: str, story_context: Optional[str] = None) -> Dict[str, Any]:
    """
    Runs the 3-Reviewer Tribunal in PARALLEL.
    Aggregates results from Prose, Redundancy, and Arc critics.
    """
    from config import CRITIC_MODEL
    import concurrent.futures
    
    # 1. Define the 3 tasks
    def run_prose():
        out = call_ollama([
            {"role": "system", "content": PROSE_CRITIC_PROMPT},
            {"role": "user", "content": f"SCENE:\n{text}"}
        ], model=CRITIC_MODEL, json_mode=True)
        return extract_clean_json(out) or {"prose_score": 50, "prose_fix": "Prose review failed."}

    def run_redundancy():
        out = call_ollama([
            {"role": "system", "content": REDUNDANCY_CRITIC_PROMPT},
            {"role": "user", "content": f"SCENE:\n{text}"}
        ], model=CRITIC_MODEL, json_mode=True)
        return extract_clean_json(out) or {"redundancy_score": 50, "redundancy_fix": "Redundancy review failed."}

    def run_arc():
        context_block = f"STORY CONTEXT:\n{story_context}\n\n" if story_context else ""
        out = call_ollama([
            {"role": "system", "content": ARC_CRITIC_PROMPT},
            {"role": "user", "content": f"{context_block}SCENE:\n{text}"}
        ], model=CRITIC_MODEL, json_mode=True)
        return extract_clean_json(out) or {"arc_score": 50, "arc_fix": "Arc review failed.", "irreversible_change": "UNKNOWN"}

    # 2. Execute in parallel
    print("\n   ⚖️  Summoning Parallel Tribunal (3 Agents)...")
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

SELECTOR_PROMPT = """
ROLE: You are the EDITOR-IN-CHIEF. You have 3 drafts of the same scene.
Your job is to select the BEST one for publication.

CRITERIA for SELECTION:
1. VOICE: Which draft has the most specific, grounded narrative voice?
2. SHOWING: Which draft avoids "filter words" (he saw, she felt) and uses sensory details?
3. LOGIC: Which draft follows the prompt constraints most accurately?

OUTPUT FORMAT (JSON ONLY):
{
  "best_draft_index": <int 1, 2, or 3>,
  "reasoning": "Brief explanation of why this draft won."
}
"""

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


WRITER_FRAME_PROMPT = """
ROLE: You are a narrative reasoning engine AND a contemporary fiction author.

═══════════════════════════════════════════════════════════════════
POV CONSTRAINT (FIX #2 - MANDATORY)
═══════════════════════════════════════════════════════════════════
This story is written in: {{pov}}
- third_limited: Use "he/she/they" pronouns ONLY. NEVER use "I" or "my" or "we".
- first_person: Use "I/my" pronouns consistently.
- third_omniscient: Narrator may describe multiple characters' thoughts.

VIOLATION = AUTOMATIC FAILURE. If the POV is third_limited, any sentence 
starting with "I " or containing "my " (as possessive) is WRONG.

═══════════════════════════════════════════════════════════════════
CHARACTER RELATIONSHIPS (FIX #3 - DO NOT CONTRADICT)
═══════════════════════════════════════════════════════════════════
{{character_relationships}}

HARD RULES:
- Characters DO NOT change age, gender, or relationship type mid-story.
- If Maria is Paul's romantic partner, she CANNOT become his daughter.
- If a character is dead, they CANNOT appear alive without clear resurrection.
- Maintain consistent roles from scene 1 to the end.

═══════════════════════════════════════════════════════════════════
PROTOCOL: SELF-CORRECTION (You MUST follow this)
═══════════════════════════════════════════════════════════════════
1. You MUST <think> before writing.
2. In your thought process, you MUST explicitly verify:
   - TIMELINE: Is current_time = {{current_time}}? Have I already written this timestamp?
   - EXHAUSTION: Does dialogue/action match the character's current fatigue level?
   - REPETITION: Am I accidentally repeating the previous scene's action or counting sequence?
   - PHYSICS: Is the character's posture ({{posture}}) accurate? Can they stand if in deep water?
   - PROGRESSION: What IRREVERSIBLE change happens in this scene?
   - POV CHECK: Am I using the correct pronouns for {{pov}}?
6. HALLUCINATION ANCHOR: {{protagonist_name}} is {{protagonist_role}}.
   - When remembering the past, the character remembers their actual backstory (from manifest).
   - Stay true to the genre and setting defined in the story profile. Do NOT import tropes from unrelated genres.
7. If you catch an error in your thoughts, CORRECT IT before outputting prose.
8. DO NOT output ratings, scores, critiques, or meta-commentary in the final text.

PROCESS (After self-correction):
1. <think> - Reason, check constraints above, fix any issues in your head
2. <plan> - Beat-by-beat: opening image → tension builds → turn → consequence
3. <write> - Output ONLY the final polished prose

PROSE RULES:
- DEEP POV only: render perception through what the character would notice and how they'd phrase it.
- SHOW, DON'T TELL: no explaining feelings; reveal via behavior, choices, micro-actions, sensory anchors, and omission.
- NO FILTER WORDS: eliminate "he saw / she felt / he noticed / he realized / she thought".
- CONCRETE OVER ABSTRACT: specific nouns, grounded verbs.
- ONE SHARP DETAIL PER SENTENCE: avoid laundry-lists of description.
- DIALOGUE SUBTEXT: characters do not say what they mean; desire leaks through avoidance, control, baiting, deflection, tenderness, or silence.
- IRREVERSIBLE CHANGE: The scene MUST end with the situation fundamentally different from the start.

QUALITY CONTROL (CRITICAL):
1. **NEGATIVE CONSTRAINT:** You are FORBIDDEN from outputting "Scores," "Tribunal Ratings," "[Tribunal Scores: ...]" or any meta-commentary in the prose. PROSE ONLY.
2. **PHYSICS CHECK:** Refer to the world state 'posture' variable:
   - IF 'Treading water': Character CANNOT stand, kneel, or step. Vertical, fluid movement only.
   - IF 'On Boat': Character feels roll/pitch.
   - IF 'Swimming': Body horizontal, arms/legs in motion.

ANTI-LOOPING PROTOCOL:
- After EVERY scene, you must advance the narrative timeline.
- IF you just wrote "Paul lets go of the buoy", THEN the next scene MUST be "Paul is swimming".
- NEVER write the same plot beat twice.
- Do NOT rewrite a timestamp. If 02:42 is done, move to 02:45.

STATE MANAGEMENT PROTOCOL:
After completing the scene prose, you MUST output a YAML block to advance the story time:

```yaml
UPDATE_STATE:
  current_time: "02:55 AM"
  current_location: "Drifting North, 200 yards from buoy"
  posture: "Treading water"
```
calculate the new time based on scene duration. If nothing changed, the scene FAILED.

CRITICAL: If the scene ends the same as it started, you have FAILED. Something must change that cannot be undone.
"""


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
    
    prompt = f"""You are a scene architect. Plan what happens in this scene with precision.

<think>
1. What is the character's exact situation RIGHT NOW? (Location, emotional state, immediate problem)
2. What MUST be different by the end of this scene? (Irreversible change)
3. What could go wrong? What unexpected element creates the turn?
4. How do we avoid repeating what happened in recent scenes?
</think>

SCENE GOAL: {scene_goal}

BEFORE STATE (how scene starts):
{before_state if before_state else f"Location: {current_loc}, Time: {current_time}"}

AFTER STATE (how scene MUST end - different from before):
{after_state if after_state else "Must be determined - something irreversible happens"}

CHARACTERS: {', '.join(char_names) if char_names else 'To be shown through action'}

═══════════════════════════════════════════════════════════════════
FIX #5: FULL STORY CONTEXT (Last 10 scenes)
═══════════════════════════════════════════════════════════════════
{all_scenes_block}

═══════════════════════════════════════════════════════════════════
RECENT SCENES (DO NOT REPEAT THESE):
═══════════════════════════════════════════════════════════════════
{anti_repetition_block}

═══════════════════════════════════════════════════════════════════
FIX #6: SCENE DIVERSITY RULES (MANDATORY)
═══════════════════════════════════════════════════════════════════
1. Each scene MUST introduce a NEW element: new location, new character action, new revelation.
2. Do NOT repeat the same dominant imagery (waves, fog, cold) without transformation.
3. If recent scenes focused on physical sensation, this scene focuses on dialogue or memory.
4. If recent scenes were introspective, this scene has external conflict.
5. VARY THE RHYTHM: short tense scenes, then longer contemplative ones.

CURRENT STAKES: {json.dumps(arc_ledger.get('stakes', [])[-3:], indent=2)}

UNRESOLVED TENSIONS: {json.dumps(arc_ledger.get('unresolved_questions', [])[-3:], indent=2)}

Return JSON ONLY:
{{
  "before_state": "Exact character situation at scene START",
  "after_state": "Exact character situation at scene END (MUST BE DIFFERENT)",
  "irreversible_change": "What cannot be undone after this scene",
  "want": "What the POV character actively pursues",
  "obstacle": "Specific thing that blocks them",
  "turn": "The unexpected shift - new info, betrayal, discovery, choice",
  "consequence": "The price paid or new pressure created",
  "beats": [
    "Opening image - ground us in the moment",
    "Rising tension - the obstacle manifests",
    "The turn - everything shifts",
    "Consequence - the irreversible change locks in"
  ],
  "subtext_hook": "What is NOT said but understood",
  "anti_repetition_note": "How this scene differs from recent scenes",
  "diversity_note": "What NEW element does this scene introduce?"
}}
"""
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




