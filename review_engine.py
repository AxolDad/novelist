"""
review_engine.py — Human-in-the-Loop Review System

Handles chapter review timeout, AI fallback review, and checkpoint logic.
"""

import os
import threading
from typing import Optional

from config import (
    CRITIC_MODEL,
    HUMAN_REVIEW_TIMEOUT,
    MANUSCRIPT_EXCERPT_CHARS,
    UI_BANNER_WIDTH
)
from ollama_client import call_ollama
from logger import logger




def input_with_timeout(prompt: str, timeout_seconds: int = HUMAN_REVIEW_TIMEOUT) -> Optional[str]:
    """
    Get user input with timeout. Returns None if timeout occurs.
    Works on Windows (no select.select on stdin).
    """
    result = [None]
    input_received = threading.Event()
    
    def get_input():
        try:
            result[0] = input(prompt)
            input_received.set()
        except EOFError:
            result[0] = ""
            input_received.set()
    
    thread = threading.Thread(target=get_input, daemon=True)
    thread.start()
    
    # Wait for either input or timeout
    got_input = input_received.wait(timeout=timeout_seconds)
    
    if not got_input:
        return None  # Timeout
    return result[0]


def generate_ai_chapter_review(manuscript_path: str) -> str:
    """
    Generate an AI review of the chapter when human doesn't respond.
    Uses AUTO_REVIEW_PROVIDER and AUTO_REVIEW_MODEL from config.
    """
    from config import AUTO_REVIEW_PROVIDER, AUTO_REVIEW_MODEL, AUTO_REVIEW_PROMPT
    from config import OPENAI_API_KEY, OPENAI_BASE_URL
    
    try:
        with open(manuscript_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Get last excerpt from manuscript
        excerpt = content[-MANUSCRIPT_EXCERPT_CHARS:] if len(content) > MANUSCRIPT_EXCERPT_CHARS else content
        
        messages = [
            {"role": "system", "content": AUTO_REVIEW_PROMPT},
            {"role": "user", "content": f"CHAPTER EXCERPT:\n\n{excerpt}"}
        ]
        
        # Route to appropriate provider
        if AUTO_REVIEW_PROVIDER == "openai" and OPENAI_API_KEY:
            # Use OpenAI API directly
            import requests
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": AUTO_REVIEW_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 500
            }
            response = requests.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            if response.status_code == 200:
                data = response.json()
                review = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return review or "Auto-review unavailable. Continuing..."
            else:
                return f"OpenAI API error: {response.status_code}"
        else:
            # Use standard call_ollama (local or configured provider)
            review = call_ollama(messages, model=AUTO_REVIEW_MODEL)
            return review or "Auto-review unavailable. Continuing..."
    except Exception as e:
        return f"Auto-review skipped: {e}"


def run_chapter_checkpoint(
    manuscript_path: str,
    current_chapter: int,
    current_scene_count: int,
    word_count: int,
    target_words: int
) -> bool:
    """
    Run chapter checkpoint with human review or AI fallback.
    
    Returns:
        True if should break/pause, False if should continue
    """
    progress_pct = (word_count / target_words * 100) if target_words > 0 else 0
    
    print("\n" + "="*UI_BANNER_WIDTH)
    print(f"📖 CHAPTER {current_chapter} COMPLETE ({current_scene_count} scenes total)")
    print("="*UI_BANNER_WIDTH)
    
    print(f"\n📊 Progress: {word_count:,} / {target_words:,} words ({progress_pct:.1f}%)")
    print(f"📄 Manuscript: {manuscript_path}")
    print(f"\n💡 Review the chapter and provide feedback to improve quality.")
    print(f"   Press ENTER to continue, or type 'pause' to stop for detailed review.")
    print(f"   (Auto-continuing in {HUMAN_REVIEW_TIMEOUT // 60} minutes if no response)\n")
    
    try:
        user_input = input_with_timeout("   > ", HUMAN_REVIEW_TIMEOUT)
        
        if user_input is None:
            # Timeout occurred - generate AI review and continue
            logger.info("Human review timed out. Generating AI review.")
            print("\n   ⏰ No response received. Generating AI review...")
            ai_review = generate_ai_chapter_review(manuscript_path)
            print(f"\n   🤖 AUTO-REVIEW:\n   {ai_review}\n")
            print("   ▶️  Auto-continuing to next chapter...")
            logger.info("Auto-continuing to next chapter.")
            return False  # Continue
        elif user_input.strip().lower() in ('pause', 'stop', 'review', 'p', 's', 'r'):
            logger.info("Human requested pause for review.")
            print("\n⏸️  Pausing for human review.")
            print(f"   Review manuscript at: {manuscript_path}")
            print("   Make any edits directly, then restart the agent to continue.")
            print("="*UI_BANNER_WIDTH + "\n")
            return True  # Break/pause
        else:
            logger.info("Human approved valid chapter.")
            print("   ▶️  Continuing to next chapter...")
            return False  # Continue
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        print("\n⏹️  Interrupted by user. Exiting...")
        return True  # Break/pause
