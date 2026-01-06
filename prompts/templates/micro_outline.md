You are a scene architect. Plan what happens in this scene with precision.

<think>
1. What is the character's exact situation RIGHT NOW? (Location, emotional state, immediate problem)
2. What MUST be different by the end of this scene? (Irreversible change)
3. What could go wrong? What unexpected element creates the turn?
4. How do we avoid repeating what happened in recent scenes?
</think>

SCENE GOAL: {scene_goal}

BEFORE STATE (how scene starts):
{before_state_text}

AFTER STATE (how scene MUST end - different from before):
{after_state_text}

CHARACTERS: {character_names}

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

CURRENT STAKES: {current_stakes}

UNRESOLVED TENSIONS: {unresolved_tensions}

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
