import config

def test_config_essential_vars_set():
    """Ensure critical configuration variables are loaded."""
    # These often map to .env or defaults
    assert config.LLM_PROVIDER
    assert config.OLLAMA_BASE_URL
    assert config.WRITER_MODEL

def test_config_paths():
    """Ensure configured file paths are strings."""
    assert isinstance(config.MANIFEST_FILE, str)
    assert isinstance(config.STATE_FILE, str)
    assert isinstance(config.CHAR_BIBLE_FILE, str)

def test_prompts_in_config():
    """Ensure prompts were loaded into config variables successfully."""
    # These should contain the loaded text, not None or empty
    assert config.AUTO_REVIEW_PROMPT
    assert "review" in config.AUTO_REVIEW_PROMPT.lower()
    
    # Check that Architect prompt loaded
    assert config.ARCHITECT_SYSTEM_PROMPT
    assert "ROGUE_SYSTEM_PROMPT" in locals() or hasattr(config, "ROGUE_SYSTEM_PROMPT")

def test_magic_number_centralization():
    """Ensure key magic numbers are accessible in config."""
    assert hasattr(config, "UI_BANNER_WIDTH")
    assert hasattr(config, "TRIBUNAL_PASS_SCORE")
    assert isinstance(config.UI_BANNER_WIDTH, int)
