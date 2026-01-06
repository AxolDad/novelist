"""
ui_helpers.py — Console UI Helpers

Provides formatted console output, progress display, and status messages.
"""

import os
import time
from typing import Any, Dict, Optional


# ------------------------------------------------------------------
#  CONSOLE FORMATTING
# ------------------------------------------------------------------

def print_banner(text: str, width: int = 60) -> None:
    """Print a banner with centered text."""
    print("\n" + "=" * width)
    print(text.center(width))
    print("=" * width)


def print_section(title: str, char: str = "-", width: int = 60) -> None:
    """Print a section header."""
    print(f"\n{char * width}")
    print(f" {title}")
    print(char * width)


def print_progress(current: int, total: int, label: str = "Progress") -> None:
    """Print a progress bar."""
    pct = (current / total * 100) if total > 0 else 0
    bar_width = 30
    filled = int(bar_width * pct / 100)
    bar = "█" * filled + "░" * (bar_width - filled)
    print(f"   {label}: [{bar}] {pct:.1f}% ({current:,}/{total:,})")


def print_model_info(provider: str, writer: str, critic: str) -> None:
    """Print LLM configuration info."""
    print(f"✅ Connected to {provider.upper()}")
    print(f"   Writer: {writer}")
    print(f"   Critic: {critic}")


def print_story_header(title: str, word_count: int, target_words: int) -> None:
    """Print story info header."""
    pct = (word_count / target_words * 100) if target_words > 0 else 0
    print(f"\n📘 Story: {title}")
    print(f"   Words: {word_count:,} / {target_words:,} ({pct:.1f}%)")


# ------------------------------------------------------------------
#  STATUS MESSAGES
# ------------------------------------------------------------------

def status_drafting(scene_title: str) -> None:
    """Print drafting status."""
    print(f"\n✍️  Drafting: {scene_title}")


def status_tribunal(attempt: int, max_attempts: int, arc_mode: str = "Full") -> None:
    """Print Tribunal status."""
    print(f"\n   ⚖️  Summoning Parallel Tribunal (3 Agents)... [Arc: {arc_mode}]")


def status_scores(prose: int, redundancy: int, arc: int, attempt: int) -> None:
    """Print Tribunal scores."""
    print(f"   📊 Tribunal Scores: Prose={prose} | Redundancy={redundancy} | Arc={arc} (Attempt {attempt})")


def status_pass() -> None:
    """Print pass status."""
    print("   ✅ ALL THREE CRITICS SATISFIED.")


def status_fail(reason: str) -> None:
    """Print fail status with reason."""
    print(f"   ❌ No draft passed Tribunal after max attempts. Last issue: {reason}")


def status_world_update() -> None:
    """Print world state update notification."""
    print("🌍 World State Updated.")


def status_drift(has_drift: bool) -> None:
    """Print character drift status."""
    print("   🧪 Running character drift check...")
    if has_drift:
        print("   🧷 Drift found. Enforcing consistency rewrite...")


# ------------------------------------------------------------------
#  TIMING HELPER
# ------------------------------------------------------------------

def breath(seconds: float = 1.25) -> None:
    """Brief pause to let the system breathe."""
    time.sleep(seconds)
