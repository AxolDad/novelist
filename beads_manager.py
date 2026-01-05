"""
beads_manager.py — Beads Task Management

Handles all interaction with the Beads issue tracking system including:
- Running bd commands
- Syncing the database
- Parsing status output
"""

def extract_json_from_mixed_output(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON object from text that might contain headers/logs."""
    if not text:
        return None
    try:
        # Fast path: strictly JSON
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find { ... }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
    return None


def parse_bd_status_counts(status_text: str) -> Dict[str, int]:
    """Parse `bd status` output (JSON or text) to count issues."""
    if not status_text:
        return {}

    # 1. Try JSON parsing (Best for `bd status --json`)
    data = extract_json_from_mixed_output(status_text)
    if data:
        summary = data.get("summary", {})
        return {
            "total": int(summary.get("total_issues", 0)),
            "open": int(summary.get("open_issues", 0)),
            "in_progress": int(summary.get("in_progress_issues", 0)),
            "blocked": int(summary.get("blocked_issues", 0)),
            "closed": int(summary.get("closed_issues", 0)),
            "ready": int(summary.get("ready_issues", 0)),
        }

    # 2. Fallback: Robust Regex Parsing (for human output)
    # Handles "Total Issues: 5", "Total: 5", "open: 2" case-insensitively
    counts: Dict[str, int] = {}
    
    def grab(patterns: List[str]) -> int:
        for p in patterns:
            # Look for Pattern + colon + number
            # e.g. "Total Issues  : 12"
            m = re.search(rf"{p}\s*:\s*(\d+)", status_text, re.IGNORECASE)
            if m:
                return int(m.group(1))
        return 0

    counts["total"] = grab(["Total Issues", "Total"])
    counts["open"] = grab(["Open", "Open Issues"])
    counts["in_progress"] = grab(["In Progress", "In-Progress"])
    counts["blocked"] = grab(["Blocked", "Blocked Issues"])
    counts["closed"] = grab(["Closed", "Closed Issues"])
    counts["ready"] = grab(["Ready", "Ready to Work"])
    
    return counts


def beads_all_work_closed(status_text: str) -> bool:
    """True when bd reports there are issues but none remain open/in-progress/blocked/ready."""
    c = parse_bd_status_counts(status_text)
    if not c:
        return False
        
    total = c.get("total", 0)
    if total <= 0:
        # Safety: If total is 0, we might have failed to parse, OR there are genuinely 0 issues.
        # But if we failed to parse, 'open' is also 0. 
        # Risky fallback: if the text contains "Total", assume we parsed it correctly as 0.
        # If text doesn't contain "Total", assume parse failure and return False (don't stop).
        if "total" in status_text.lower():
            return False # 0 total issues = nothing to do? Or just started? Safe to say "not done"
        return False # Parse failure safety
        
    return (
        c.get("open", 0) == 0
        and c.get("in_progress", 0) == 0
        and c.get("blocked", 0) == 0
        and c.get("ready", 0) == 0
    )


# ------------------------------------------------------------------
#  EXECUTION
# ------------------------------------------------------------------

import subprocess
import os
from typing import List

def run_beads(args: List[str]) -> str:
    """Run a Beads command and return stdout."""
    cmd = ["bd"] + args
    try:
        # Check if we should enforce direct mode explicitly?
        # config.py sets os.environ["BD_DIRECT"] = "1"
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        if result.returncode != 0:
             # Just return empty or log? For robustness we return stderr if needed,
             # but caller usually expects stdout.
             pass
        return result.stdout.strip()
    except FileNotFoundError:
        print("⚠️ Beads (bd) binary not found.")
        return ""
    except Exception as e:
        print(f"❌ Beads Error: {e}")
        return ""

def force_sync():
    """Force a Beads database sync."""
    run_beads(["sync"])

def get_task_id(search_text: str = "") -> str:
    """
    Get current task ID. 
    Dummy implementation since novelist.py imports it but doesn't strictly use it yet.
    """
    return "1"
