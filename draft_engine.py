"""
draft_engine.py — Parallel Draft Generation

Handles multi-temperature draft generation and editor selection.
"""

import concurrent.futures
from typing import Optional

from config import WRITER_MODEL
from ollama_client import call_ollama
from prompts import select_best_draft
from logger import logger


def generate_parallel_drafts(system_context: str, user_prompt: str) -> Optional[str]:
    """Generates 3 drafts with different temperatures and selects the best one."""
    messages = [
        {"role": "system", "content": system_context},
        {"role": "user", "content": user_prompt}
    ]
    
    # Temperatures: 0.7 (Safe), 0.9 (Creative), 1.1 (Chaotic/Innovative)
    temps = [0.7, 0.9, 1.1]
    
    logger.info(f"Drafting 3 variants in parallel (Temps: {temps})...")
    
    drafts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(call_ollama, messages, WRITER_MODEL, False, 32768, None, t)
            for t in temps
        ]
        
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                drafts.append(res)
    
    if not drafts:
        return None
        
    if len(drafts) == 1:
        return drafts[0]
        
    logger.info(f"Evaluating {len(drafts)} drafts via Editor-in-Chief...")
    selection = select_best_draft(drafts)
    idx = selection.get("best_draft_index", 1) - 1
    reason = selection.get("reasoning", "No valid reason provided.")
    
    # Safety Check
    if idx < 0 or idx >= len(drafts):
        idx = 0
        
    logger.info(f"Selected Draft {idx+1}: {reason[:100]}...")
    return drafts[idx]
