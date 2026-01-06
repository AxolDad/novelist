"""
ollama_client.py — LLM API Communication

Handles all communication with LLM APIs including:
- Local Ollama API calls
- OpenAI-compatible API calls (OpenAI, Together, Groq, etc.)
- Connection health checks
- JSON extraction from responses
"""

import json
import re
import time
from typing import Any, Dict, List, Optional

import requests

from config import (
    LLM_PROVIDER,
    OLLAMA_URL,
    OLLAMA_TAGS_URL,
    OLLAMA_HTTP_TIMEOUT,
    OLLAMA_MAX_RETRIES,
    OLLAMA_RETRY_BACKOFF_BASE,
    OLLAMA_RETRY_JITTER,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    WRITER_MODEL,
    OLLAMA_CHECK_TIMEOUT,
    DEFAULT_NUM_CTX,
    CONTEXT_RESERVE_TOKENS,
    CONTEXT_MIN_BUDGET_TOKENS,
    TOKEN_EST_CHARS_PER_TOKEN,
    WRITER_TEMP_DEFAULT,
    CRITIC_TEMP_DEFAULT,
    CONTEXT_SLASH_RATIO
)
from logger import logger


def extract_clean_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Robustly extract JSON from text, handling <think> blocks, markdown, and 'dirty' output.
    Uses brace counting to find the valid JSON object.
    """
    if not text:
        return None

    # 1. Remove <think> blocks (Reasoning Models)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    
    # 2. Clean Markdown
    text = re.sub(r"```json", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text)
    
    # 3. First pass: Try standard extraction of outer-most braces
    # This works for 90% of cases where the response IS just JSON or JSON wrapped in text
    cleaned_text = text.strip()
    start = cleaned_text.find('{')
    end = cleaned_text.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        candidate = cleaned_text[start:end+1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # 4. Fallback: Brace Counting (Handles "Here is JSON: {...} and here is more text")
            pass
            
    # 5. Iterative Finder: Scan for all '{' and try to find matching '}'
    # This handles cases where greedy matching failed due to multiple separate objects or corruption
    candidates = []
    
    idx = 0
    while idx < len(text):
        start = text.find('{', idx)
        if start == -1:
            break
            
        # Count braces to find matching end
        balance = 0
        for i in range(start, len(text)):
            char = text[i]
            if char == '{':
                balance += 1
            elif char == '}':
                balance -= 1
                
            if balance == 0:
                # Potential JSON found
                candidate = text[start:i+1]
                try:
                    candidates.append(json.loads(candidate))
                    idx = i  # Advance past this object
                    break
                except json.JSONDecodeError:
                    # Keep trying (nesting issues?)
                    continue
        else:
             # Unbalanced or failed to find end
             idx = start + 1
             
    if candidates:
        # heuristic: return the largest JSON object found (most likely the main payload)
        return max(candidates, key=lambda x: len(str(x)))

    # 6. Last Ditch: Regex to fix common "lazy" JSON (trailing commas, unquoted keys)
    # Note: Only trying this on the outer bounds candidate from step 3
    if start != -1 and end != -1:
        candidate = text[start:end+1]
        try:
            # Fix trailing commas
            candidate = re.sub(r",\s*}", "}", candidate)
            candidate = re.sub(r",\s*]", "]", candidate)
            return json.loads(candidate)
        except Exception:
            pass

    return None


def check_ollama_connection() -> bool:
    """Quick 'is Ollama alive?' check using /api/tags."""
    if LLM_PROVIDER != "ollama":
        # For commercial APIs, just check if API key is set
        return bool(OPENAI_API_KEY)
    try:
        r = requests.get(OLLAMA_TAGS_URL, timeout=OLLAMA_CHECK_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def _call_ollama_local(
    messages: List[Dict[str, str]],
    model: str,
    json_mode: bool,
    num_ctx: int,
    num_predict: Optional[int],
    temp: float
) -> Optional[str]:
    """Make API call to local Ollama instance."""
    options = {"num_ctx": num_ctx, "temperature": temp}
    if num_predict is not None:
        options["num_predict"] = num_predict

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options
    }
    if json_mode:
        payload["format"] = "json"

    # logger.debug(f"Sending to {OLLAMA_URL} | Model: {repr(payload['model'])}")
    response = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_HTTP_TIMEOUT)
    if response.status_code != 200:
        logger.error(f"API Error Details: {response.text}")
    response.raise_for_status()
    content = response.json()['message']['content']

    # Print thinking ONLY for Writer (optional visibility)
    if model == WRITER_MODEL:
        think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL | re.IGNORECASE)
        if think_match:
            snippet = think_match.group(1).strip()
            # Still using visible output here as it's a deliberate user-facing feature
            # But logging it as DEBUG
            logger.debug(f"WRITER THINKING snippet: {snippet[:200]}...")
            print(f"\n\033[93m💭 WRITER THINKING (snippet):\n{snippet[:500]}...\033[0m\n")
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()

    return content


def _call_openai_compatible(
    messages: List[Dict[str, str]],
    model: str,
    json_mode: bool,
    temp: float
) -> Optional[str]:
    """Make API call to OpenAI-compatible endpoint."""
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temp,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    url = f"{OPENAI_BASE_URL}/chat/completions"
    response = requests.post(url, json=payload, headers=headers, timeout=OLLAMA_HTTP_TIMEOUT)
    response.raise_for_status()
    content = response.json()['choices'][0]['message']['content']
    
    return content


    return content


# ------------------------------------------------------------------
#  CONTEXT SAFETY (Token Limiting)
# ------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """
    Approximate token count (3.5 chars/token).
    Faster than real tokenization and sufficient for safety buffers.
    """
    if not text:
        return 0
    return int(len(text) / TOKEN_EST_CHARS_PER_TOKEN)


def truncate_middle(text: str, max_chars: int) -> str:
    """Smartly truncate the middle of text to fit max_chars."""
    if len(text) <= max_chars:
        return text
    
    keep = max_chars // 2
    return text[:keep] + "\n...[CONTEXT TRUNCATED FOR SAFETY]...\n" + text[-keep:]


def enforce_context_safety(messages: List[Dict[str, str]], max_ctx: int = 30000) -> List[Dict[str, str]]:
    """
    Ensure total prompt size fits within context window.
    
    STRATEGY:
    1. System prompt is SACRED (never touch).
    2. Last user message is SACRED (current instruction).
    3. Old history/context gets truncated if needed.
    """
    total_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
    
    # If safe, return as is (leave room for generation)
    if total_tokens < (max_ctx - CONTEXT_RESERVE_TOKENS):
        return messages
        
    logger.warning(f"CONTEXT WARNING: {total_tokens} tokens > limit {max_ctx}. Truncating...")
    
    # Calculate budget
    # System prompt: keep full
    # Last message: keep full
    # Middle messages: squeeze
    
    safe_messages = messages.copy()
    
    # Find indices
    sys_idx = -1
    for i, m in enumerate(safe_messages):
        if m.get("role") == "system":
            sys_idx = i
            break
            
    # Calculate non-negotiable budget
    reserved_tokens = 0
    if sys_idx != -1:
        reserved_tokens += estimate_tokens(safe_messages[sys_idx]["content"])
    
    # Last message is usually the active task
    last_idx = len(safe_messages) - 1
    if last_idx > sys_idx:
        reserved_tokens += estimate_tokens(safe_messages[last_idx]["content"])
        
    # Remaining budget for middle content
    available_tokens = (max_ctx - CONTEXT_RESERVE_TOKENS) - reserved_tokens
    if available_tokens < CONTEXT_MIN_BUDGET_TOKENS:
        # Extreme case: System + Last msg are huge. Truncate last message too.
        logger.warning("Extreme context pressure. Truncating current instruction.")
        avail_chars = int(10000 * TOKEN_EST_CHARS_PER_TOKEN) # Hard cap 10k context
        if last_idx >= 0:
            safe_messages[last_idx]["content"] = truncate_middle(safe_messages[last_idx]["content"], avail_chars)
        return safe_messages

    # Truncate middle messages
    # We allocate proportional valid chars to remaining messages
    for i, m in enumerate(safe_messages):
        if i == sys_idx or i == last_idx:
            continue
            
        content = m.get("content", "")
        # Heuristic: Cut middle content proportionally
        current_len = len(content)
        target_len = int(current_len * CONTEXT_SLASH_RATIO)
        safe_messages[i]["content"] = truncate_middle(content, target_len)
    
    return safe_messages


def call_ollama(
    messages: List[Dict[str, str]],
    model: str = WRITER_MODEL,
    json_mode: bool = False,
    num_ctx: int = DEFAULT_NUM_CTX,
    num_predict: Optional[int] = None,
    temperature: Optional[float] = None
) -> Optional[str]:
    """
    Generic API call to LLM with explicit timeout + retries.
    Routes to Ollama or OpenAI-compatible API based on LLM_PROVIDER config.
    """
    # 1. ENFORCE CONTEXT SAFETY TO PROTECT SYSTEM PROMPT
    safe_messages = enforce_context_safety(messages, max_ctx=num_ctx)
    
    if temperature is not None:
        temp = temperature
    else:
        temp = WRITER_TEMP_DEFAULT if model == WRITER_MODEL else CRITIC_TEMP_DEFAULT

    last_err = None
    for attempt in range(1, OLLAMA_MAX_RETRIES + 1):
        try:
            if LLM_PROVIDER == "ollama":
                return _call_ollama_local(safe_messages, model, json_mode, num_ctx, num_predict, temp)
            else:
                return _call_openai_compatible(safe_messages, model, json_mode, temp)

        except Exception as e:
            last_err = e
            logger.error(f"API Error (Attempt {attempt}/{OLLAMA_MAX_RETRIES}): {e}")
            if attempt < OLLAMA_MAX_RETRIES:
                backoff = (OLLAMA_RETRY_BACKOFF_BASE ** (attempt - 1)) + OLLAMA_RETRY_JITTER
                time.sleep(backoff)

    return None
