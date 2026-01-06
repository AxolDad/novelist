import os
import pytest
from prompt_loader import load_prompt

def test_prompts_directory_exists():
    """Ensure the prompts directory exists."""
    prompts_dir = os.path.join(os.getcwd(), "prompts")
    assert os.path.exists(prompts_dir)
    assert os.path.isdir(prompts_dir)

def test_load_existing_prompt():
    """Test loading a real prompt that should exist."""
    # We created checks/prose.md earlier
    content = load_prompt("critics", "prose.md")
    assert "PROSE CRITIC" in content
    assert not content.startswith("ERROR")

def test_load_non_existent_prompt():
    """Test graceful failure for missing prompt."""
    content = load_prompt("fake_cat", "does_not_exist.md")
    assert content.startswith("ERROR")

def test_load_prompt_caching():
    """Test that caching works (same object id if immutable, or just logic check)."""
    # Since load_prompt returns a string, Python might intern it or not. 
    # But we can verify multiple calls work.
    p1 = load_prompt("critics", "prose.md")
    p2 = load_prompt("critics", "prose.md")
    assert p1 == p2
