"""
manuscript_polisher.py — Final Manuscript Cleanup & Formatting

Runs after all scenes are complete but before novel is marked done.
Uses The Architect (DeepSeek R1) for structural organization:
- Organizes scenes into proper chapters
- Adds chapter headers and section breaks
- Creates clean front matter
- Exports publication-ready manuscript
"""

import os
import re
import json
from typing import Dict, Any, List, Optional

from config import WRITER_MODEL, MODEL_PRESETS
from ollama_client import call_ollama, extract_clean_json
from file_utils import safe_read_json
from logger import logger

# Use The Architect for structural tasks
ARCHITECT_MODEL = MODEL_PRESETS["architect"]["model"]


def load_raw_manuscript(manuscript_path: str) -> str:
    """Load the raw manuscript file."""
    if not os.path.exists(manuscript_path):
        return ""
    with open(manuscript_path, "r", encoding="utf-8") as f:
        return f.read()


def clean_formatting_artifacts(text: str) -> str:
    """Remove common formatting artifacts from manuscript."""
    # Remove duplicate horizontal rules
    text = re.sub(r"(\n---\n){2,}", "\n---\n", text)
    
    # Remove empty sections
    text = re.sub(r"##\s*\n+##", "##", text)
    
    # Remove tribunal score lines (safety net)
    text = re.sub(r"\[Tribunal Scores?:.*?\]", "", text, flags=re.IGNORECASE)
    
    # Remove UPDATE_STATE blocks
    text = re.sub(r"```yaml\n.*?UPDATE_STATE:.*?```\s*", "", text, flags=re.DOTALL)
    
    # Normalize whitespace
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    
    # Remove trailing whitespace from lines
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    
    return text.strip()


def analyze_manuscript_structure(manuscript: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """
    Use The Architect to analyze manuscript and propose chapter structure.
    Returns a structure plan with chapter breaks and titles.
    """
    title = manifest.get("title", "Untitled")
    target_chapters = manifest.get("chapters", [])
    num_chapters = len(target_chapters) if target_chapters else 3
    
    # Count existing scene headers
    scene_headers = re.findall(r"^## .+$", manuscript, re.MULTILINE)
    
    analysis_prompt = f"""
TASK: Analyze this manuscript and propose a chapter structure.

MANUSCRIPT TITLE: {title}
CURRENT SCENE COUNT: {len(scene_headers)}
TARGET CHAPTER COUNT: {num_chapters}

SCENE HEADERS FOUND:
{chr(10).join(scene_headers[:20])}

INSTRUCTIONS:
1. Group related scenes into logical chapters
2. Propose chapter titles based on narrative arc
3. Identify natural break points (time jumps, location changes, POV shifts)

OUTPUT FORMAT (JSON):
{{
  "proposed_chapters": [
    {{
      "chapter_number": 1,
      "title": "Chapter Title",
      "scenes": ["Scene Header 1", "Scene Header 2"],
      "break_reason": "Why this is a natural chapter break"
    }}
  ],
  "front_matter": {{
    "title": "{title}",
    "subtitle": "Optional subtitle if appropriate",
    "epigraph": "Optional opening quote if thematically appropriate"
  }},
  "formatting_notes": "Any specific formatting recommendations"
}}
"""
    
    response = call_ollama(
        [{"role": "user", "content": analysis_prompt}],
        model=ARCHITECT_MODEL,
        json_mode=True
    )
    
    structure = extract_clean_json(response)
    if not structure:
        # Fallback: simple chapter division
        scenes_per_chapter = max(1, len(scene_headers) // max(1, num_chapters))
        structure = {
            "proposed_chapters": [
                {
                    "chapter_number": i + 1,
                    "title": f"Chapter {i + 1}",
                    "scenes": scene_headers[i*scenes_per_chapter:(i+1)*scenes_per_chapter]
                }
                for i in range(num_chapters)
            ],
            "front_matter": {"title": title}
        }
    
    return structure


def format_chapter_header(chapter_num: int, title: str) -> str:
    """Format a chapter header in markdown."""
    return f"\n\n---\n\n# Chapter {chapter_num}: {title}\n\n"


def reorganize_into_chapters(manuscript: str, structure: Dict[str, Any]) -> str:
    """
    Reorganize manuscript into proper chapter structure.
    """
    chapters = structure.get("proposed_chapters", [])
    front_matter = structure.get("front_matter", {})
    
    # Build front matter
    output_parts = []
    
    # Title page
    title = front_matter.get("title", "Untitled")
    output_parts.append(f"# {title}\n")
    
    if front_matter.get("subtitle"):
        output_parts.append(f"*{front_matter['subtitle']}*\n")
    
    if front_matter.get("epigraph"):
        output_parts.append(f"\n> {front_matter['epigraph']}\n")
    
    output_parts.append("\n---\n")
    
    # Process each chapter
    for chapter in chapters:
        chapter_num = chapter.get("chapter_number", 1)
        chapter_title = chapter.get("title", f"Chapter {chapter_num}")
        scenes = chapter.get("scenes", [])
        
        # Add chapter header
        output_parts.append(format_chapter_header(chapter_num, chapter_title))
        
        # Find and add each scene
        for scene_header in scenes:
            # Find the scene in the manuscript
            scene_pattern = re.escape(scene_header)
            match = re.search(
                rf"^{scene_pattern}\s*\n(.*?)(?=^## |\Z)",
                manuscript,
                re.MULTILINE | re.DOTALL
            )
            if match:
                scene_content = match.group(1).strip()
                # Convert scene header to section header (### instead of ##)
                scene_title = scene_header.replace("## ", "")
                output_parts.append(f"### {scene_title}\n\n{scene_content}\n")
    
    # Combine and clean
    final = "\n".join(output_parts)
    return clean_formatting_artifacts(final)


def polish_manuscript(
    manuscript_path: str,
    manifest: Dict[str, Any],
    output_path: Optional[str] = None,
    verbose: bool = True
) -> str:
    """
    Main entry point: Polish and format the complete manuscript.
    
    Args:
        manuscript_path: Path to raw manuscript file
        manifest: Story manifest with title, chapters, etc.
        output_path: Optional path for polished output (defaults to exports/final.md)
        verbose: Print progress messages
    
    Returns:
        Path to polished manuscript
    """
    if verbose:
        logger.info("MANUSCRIPT POLISHER")
        logger.info("Using The Architect (DeepSeek R1) for structural analysis...")
    
    # Load raw manuscript
    raw = load_raw_manuscript(manuscript_path)
    if not raw:
        if verbose:
            logger.warning("No manuscript found to polish.")
        return ""
    
    # Initial cleanup
    if verbose:
        logger.info("Cleaning formatting artifacts...")
    cleaned = clean_formatting_artifacts(raw)
    
    # Analyze structure
    if verbose:
        logger.info("Analyzing manuscript structure...")
    structure = analyze_manuscript_structure(cleaned, manifest)
    
    # Reorganize into chapters
    if verbose:
        chapters = structure.get("proposed_chapters", [])
        logger.info(f"Organizing into {len(chapters)} chapters...")
    polished = reorganize_into_chapters(cleaned, structure)
    
    # Determine output path
    if not output_path:
        # Default to exports folder
        project_dir = os.path.dirname(manuscript_path)
        exports_dir = os.path.join(project_dir, "exports")
        os.makedirs(exports_dir, exist_ok=True)
        output_path = os.path.join(exports_dir, "final_manuscript.md")
    
    # Save polished manuscript
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(polished)
    
    if verbose:
        word_count = len(re.findall(r"\b\w+\b", polished))
        logger.info(f"Polished manuscript saved: {output_path}")
        logger.info(f"Final word count: {word_count:,}")
    
    return output_path


def create_export_formats(polished_path: str, manifest: Dict[str, Any]) -> Dict[str, str]:
    """
    Create additional export formats from polished manuscript.
    Returns dict of format -> path.
    """
    exports = {"markdown": polished_path}
    
    # Read polished content
    with open(polished_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    base_dir = os.path.dirname(polished_path)
    title_slug = manifest.get("slug", "novel")
    
    # Plain text (no markdown)
    txt_path = os.path.join(base_dir, f"{title_slug}.txt")
    txt_content = re.sub(r"[#*_`]", "", content)  # Strip markdown
    txt_content = re.sub(r"\n---\n", "\n" + "="*40 + "\n", txt_content)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt_content)
    exports["text"] = txt_path
    
    return exports
