"""
quality_passes.py — Quality Enforcement

Handles all quality passes on generated prose:
- Style linting (filter words, generic verbs, clichés)
- Dialogue subtext analysis and enforcement
- Character behavioral drift detection
"""

import json
import re
from typing import Any, Dict, List, Optional

from config import CRITIC_MODEL, STATE_EXCERPT_CHARS
from ollama_client import call_ollama, extract_clean_json


# ------------------------------------------------------------------
#  OUTPUT SANITIZATION (Strip LLM meta-commentary)
# ------------------------------------------------------------------
def sanitize_llm_output(text: str) -> str:
    """
    Strip meta-commentary, thinking tags, revision explanations, 
    foreign text, and duplicate paragraphs from LLM output.
    Returns only the actual prose content.
    """
    if not text:
        return text
    
    # --- FIX #7: Remove non-ASCII characters (Chinese, etc.) ---
    # Keep basic punctuation but strip foreign scripts
    text = re.sub(r'[^\x00-\x7F\u2018\u2019\u201C\u201D\u2013\u2014]+', '', text)
    
    # --- FIX #1: Remove XML-style tags that leak through ---
    xml_tags = [
        r'</?think>',
        r'</?write>',
        r'</?plan>',
        r'</?output>',
        r'</?response>',
        r'</?scene>',
    ]
    for tag in xml_tags:
        text = re.sub(tag, '', text, flags=re.IGNORECASE)
    
    # Remove <think>...</think> blocks (with content)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove <plan>...</plan> blocks
    text = re.sub(r'<plan>.*?</plan>', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # --- System prompt leak detection ---
    system_leak_patterns = [
        r'.*calculate the new time.*',
        r'.*scene duration.*',
        r'.*UPDATE_STATE.*',
        r'.*IRREVERSIBLE CHANGE.*',
        r'.*Word count:.*',
        r'.*\[Word count:.*\].*',
        r'.*Tribunal Scores:.*',
        r'.*prose_score.*redundancy_score.*',
        r'.*NYT.*WP.*Oprah.*',  # Old scoring format
    ]
    
    # Remove lines that start with common meta-commentary patterns
    meta_patterns = [
        r'^In this (?:revised )?scene.*$',
        r'^Here is the revised.*$',
        r'^The revised scene.*$',
        r'^I\'ve (?:aimed|tried|revised).*$',
        r'^\*\s+(?:Removing|Adding|Using|Maintaining|Introducing).*$',
        r'^(?:Note|Notes):.*$',
        r'^\[Word count:.*\]$',
        r'^Each revision builds.*$',
        r'^(?:And )?[Ff]inally:.*$',
        r'^---\s*$',  # Handle separately for section breaks
        r'^The revised version.*$',
        r'^Here\'s the.*$',
        r'^Let me.*$',
        r'^I will.*$',
        r'^I need to.*$',
        r'^Okay,.*$',
        r'^Alright,.*$',
    ]
    
    lines = text.split('\n')
    cleaned_lines = []
    in_meta_block = False
    
    for line in lines:
        stripped = line.strip()
        
        # Skip system prompt leaks
        is_system_leak = False
        for pattern in system_leak_patterns:
            if re.match(pattern, stripped, re.IGNORECASE):
                is_system_leak = True
                break
        if is_system_leak:
            continue
        
        # Detect start of meta-commentary block (bullet points explaining changes)
        if stripped.startswith('* ') and any(kw in stripped.lower() for kw in ['removing', 'adding', 'using', 'maintaining', 'introducing', 'subtext', 'power dynamics']):
            in_meta_block = True
            continue
        
        # Skip empty lines in meta blocks
        if in_meta_block and not stripped:
            continue
            
        # Exit meta block when we hit real content
        if in_meta_block and stripped and not stripped.startswith('*'):
            # Check if this looks like prose (starts with capital, has length)
            if len(stripped) > 20 and stripped[0].isupper():
                in_meta_block = False
            else:
                # Skip short meta lines
                is_meta = False
                for pattern in meta_patterns:
                    if re.match(pattern, stripped, re.IGNORECASE | re.MULTILINE):
                        is_meta = True
                        break
                if is_meta:
                    continue
                in_meta_block = False
        
        # Skip lines matching meta patterns
        is_meta = False
        for pattern in meta_patterns:
            if re.match(pattern, stripped, re.IGNORECASE | re.MULTILINE):
                is_meta = True
                break
        
        if not is_meta and not in_meta_block:
            cleaned_lines.append(line)
    
    result = '\n'.join(cleaned_lines)
    
    # --- FIX #4: Remove duplicate paragraphs ---
    result = remove_duplicate_paragraphs(result)
    
    # Clean up excessive newlines
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    return result.strip()


def remove_duplicate_paragraphs(text: str) -> str:
    """Remove exact duplicate paragraphs from text."""
    paragraphs = re.split(r'\n\n+', text)
    seen = set()
    unique_paragraphs = []
    
    for para in paragraphs:
        # Normalize for comparison (strip, lowercase)
        normalized = para.strip().lower()
        # Skip very short paragraphs from dedup (like "---")
        if len(normalized) < 50:
            unique_paragraphs.append(para)
            continue
        
        if normalized not in seen:
            seen.add(normalized)
            unique_paragraphs.append(para)
        # else: skip duplicate
    
    return '\n\n'.join(unique_paragraphs)



# ------------------------------------------------------------------
#  LINTER PATTERNS
# ------------------------------------------------------------------
FILTER_WORDS = [
    r"\bhe saw\b", r"\bshe saw\b", r"\bhe felt\b", r"\bshe felt\b", 
    r"\bhe noticed\b", r"\bshe noticed\b", r"\bhe realized\b", r"\bshe realized\b", 
    r"\bhe thought\b", r"\bshe thought\b", r"\bhe wondered\b", r"\bshe wondered\b",
]

GENERIC_VERBS = [
    r"\bgot\b", r"\bwent\b", r"\blooked\b", r"\bwalked\b", r"\bturned\b", r"\bstarted\b"
]

CLICHE_PATTERNS = [
    r"\bheart (?:was )?racing\b",
    r"\bbreath (?:caught|hitched)\b",
    r"\bdead silence\b",
    r"\blet out a breath\b",
    r"\btime stood still\b",
    r"\beyes widened\b",
    r"\bfor what felt like\b",
    r"\bthe air was thick\b",
    r"\blike a punch\b",
]


def lint_text(text: str) -> Dict[str, Any]:
    """Deterministic style lint (fast, local). Returns issues list + counts."""
    issues: List[Dict[str, Any]] = []

    def count_matches(patterns: List[str], label: str) -> None:
        for pat in patterns:
            m = re.findall(pat, text, flags=re.IGNORECASE)
            if m:
                issues.append({"type": label, "pattern": pat, "count": len(m)})

    count_matches(FILTER_WORDS, "filter_word")
    count_matches(GENERIC_VERBS, "generic_verb")
    count_matches(CLICHE_PATTERNS, "cliche")

    # Repeated word heuristic (very simple)
    tokens = re.findall(r"[A-Za-z']+", text.lower())
    freq: Dict[str, int] = {}
    for t in tokens:
        if len(t) < 4:
            continue
        freq[t] = freq.get(t, 0) + 1
    repeats = sorted([(w, c) for w, c in freq.items() if c >= 10], key=lambda x: x[1], reverse=True)[:12]
    if repeats:
        issues.append({"type": "repetition", "top_repeats": repeats})

    # Sentence rhythm heuristic: too many sentences starting with "He/She/I"
    starts = re.findall(r"(?m)^\s*(He|She|I)\b", text)
    if len(starts) >= 10:
        issues.append({"type": "rhythm", "note": f"Many sentences start with {set(starts)}; vary openings."})

    return {"issue_count": len(issues), "issues": issues}


def has_dialogue(text: str) -> bool:
    """Check if text contains dialogue."""
    # Match curly quotes or straight quotes with at least 3 chars inside
    return bool(re.search(r'[\u201c\u201d"][^"\u201c\u201d]{3,}[\u201c\u201d"]', text)) or bool(re.search(r'"[^"]{3,}"', text))


def enforce_style_lint(draft: str, lint: Dict[str, Any], system_context: str) -> str:
    """LLM pass to fix lint issues without changing plot facts."""
    if lint.get("issue_count", 0) == 0:
        return draft

    prompt = f"""TASK: Revise the scene to fix these specific issues. Return ONLY prose.

ISSUES TO FIX:
{json.dumps(lint, indent=2)}

SPECIFIC FIXES REQUIRED:
- Filter words like "he saw", "she felt" → Replace with direct action/perception
- Generic verbs → Replace with precise, physical verbs
- Clichés → Replace with unique, concrete sensory detail
- Repetitive sentence openings → Vary structure

CRITICAL OUTPUT RULES:
- Output ONLY the revised scene prose
- Do NOT include explanations, bullet points, or commentary
- Do NOT start with "Here is" or "The revised scene"
- Do NOT explain what you changed
- Just output the story text, nothing else

SCENE TO REVISE:
{draft}
"""
    revised = call_ollama([
        {"role": "system", "content": system_context},
        {"role": "user", "content": prompt}
    ], model=CRITIC_MODEL)

    # Strip any meta-commentary that leaks through
    return sanitize_llm_output(revised) if revised else draft


# ------------------------------------------------------------------
#  DIALOGUE SUBTEXT
# ------------------------------------------------------------------
def build_subtext_map(draft: str, world_state: Dict[str, Any], char_bible: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Analyze dialogue for subtext opportunities."""
    prompt = f"""
Return JSON ONLY.

Analyze the dialogue and produce a subtext map.
- Identify each speaking character
- What they WANT in the exchange
- What they FEAR / avoid revealing
- The tactic they use (deflect, charm, threaten, bargain, stonewall, needle, confess, joke, etc.)
- One rewrite note to increase subtext

WORLD STATE:
{json.dumps(world_state, indent=2)}

CHARACTER BIBLE:
{json.dumps(char_bible, indent=2)}

SCENE:
{draft[:2400]}

OUTPUT JSON:
{{
  "speakers": [
    {{
      "name": "...",
      "want": "...",
      "avoid": "...",
      "tactic": "...",
      "rewrite_note": "..."
    }}
  ],
  "global_note": "One note about power / tension / implication to strengthen."
}}
"""
    out = call_ollama([{"role": "user", "content": prompt}], model=CRITIC_MODEL, json_mode=True)
    return extract_clean_json(out)


def enforce_dialogue_subtext(draft: str, subtext_map: Dict[str, Any], system_context: str) -> str:
    """Rewrite dialogue to increase subtext based on the subtext map."""
    if not subtext_map:
        return draft
    prompt = f"""TASK: Rewrite dialogue to add psychological depth. Return ONLY prose.

SUBTEXT ANALYSIS:
{json.dumps(subtext_map, indent=2)}

SPECIFIC REWRITES REQUIRED:
- Characters avoid saying what they mean directly
- Add physical business during dialogue (hands, posture, micro-actions)
- Let meaning leak through pauses, deflections, or topic changes
- Remove on-the-nose emotional statements

CRITICAL OUTPUT RULES:
- Output ONLY the revised scene prose
- Do NOT include explanations, bullet points, or commentary
- Do NOT start with "Here is" or "The revised scene"
- Do NOT explain what you changed
- Just output the story text, nothing else

SCENE TO REWRITE:
{draft}
"""
    revised = call_ollama([
        {"role": "system", "content": system_context},
        {"role": "user", "content": prompt}
    ], model=CRITIC_MODEL)
    
    # Strip any meta-commentary that leaks through
    return sanitize_llm_output(revised) if revised else draft


# ------------------------------------------------------------------
#  CHARACTER DRIFT DETECTION
# ------------------------------------------------------------------
def detect_behavioral_drift(scene_text: str, char_bible: Dict[str, Any], world_state: Dict[str, Any]) -> Dict[str, Any]:
    """Detect behavioral/voice drift from established character markers."""
    prompt = f"""
Return JSON ONLY.

Task: Detect behavioral/voice drift.
Compare the scene against the character bible markers and call out inconsistencies.
Do NOT use diagnostic labels; speak in behavioral terms.

CHARACTER BIBLE:
{json.dumps(char_bible, indent=2)}

WORLD STATE:
{json.dumps(world_state, indent=2)}

SCENE:
{scene_text[:2400]}

OUTPUT:
{{
  "drift_found": true/false,
  "notes": ["..."],
  "fix_instructions": ["Concrete rewrite instruction 1", "instruction 2"]
}}
"""
    out = call_ollama([{"role": "user", "content": prompt}], model=CRITIC_MODEL, json_mode=True)
    data = extract_clean_json(out)
    if data:
        return data
    return {"drift_found": False, "notes": [], "fix_instructions": []}


def enforce_drift_fixes(draft: str, drift_report: Dict[str, Any], system_context: str) -> str:
    """Rewrite scene to correct character drift while keeping plot facts."""
    if not drift_report.get("drift_found"):
        return draft
    fixes = drift_report.get("fix_instructions") or []
    prompt = f"""TASK: Fix character inconsistencies in this scene. Return ONLY prose.

DRIFT ISSUES FOUND:
{json.dumps(fixes, indent=2)}

SPECIFIC FIXES REQUIRED:
- Adjust character voice/diction to match established patterns
- Fix behavioral inconsistencies through action, not explanation
- Keep same plot events, just adjust how character expresses them

CRITICAL OUTPUT RULES:
- Output ONLY the revised scene prose
- Do NOT include explanations, bullet points, or commentary
- Do NOT start with "Here is" or "The revised scene"
- Do NOT explain what you changed
- Just output the story text, nothing else

SCENE TO FIX:
{draft}
"""
    revised = call_ollama([
        {"role": "system", "content": system_context},
        {"role": "user", "content": prompt}
    ], model=CRITIC_MODEL)
    
    # Strip any meta-commentary that leaks through
    return sanitize_llm_output(revised) if revised else draft
