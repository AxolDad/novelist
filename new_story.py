#!/usr/bin/env python3
"""
new_story.py — Story Project Scaffolder (safe)

Creates:
- story_manifest.json (blueprint/config; the novelist never writes back to it)

Does NOT modify:
- novelist.py
- Beads tasks
- any existing story output

Notes:
- JSON cannot contain comments. Use the "manifest_instructions" block for guidance.
- Acts are kept for backward compatibility (many seeding systems create one task per act scene).
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_LENGTH_PRESETS = {
    "microfiction": 300,
    "flash": 1000,
    "short_story": 5000,
    "long_short_story": 9000,
    "novelette": 15000,
    "novella": 30000,
    "short_novel": 60000,
    "standard_novel": 80000,
    "long_novel": 120000,
    "epic": 180000,
}

LENGTH_REFERENCE = {
    "microfiction": "6–300 words",
    "flash_fiction": "300–1,000 words",
    "short_short_story": "1,000–2,500 words",
    "short_story": "2,500–7,500 words",
    "novelette": "7,500–17,500 words",
    "novella": "17,500–40,000 words",
    "short_novel": "40,000–70,000 words",
    "standard_novel": "70,000–100,000 words",
    "long_novel": "100,000–150,000 words",
    "epic": "150,000+ words",
    "common_practical_targets": {
        "punchy_short_story": "4,000–8,000 words",
        "big_short_story": "8,000–12,000 words",
        "tight_novella": "20,000–35,000 words",
    },
}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def slugify(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "new_story"


def prompt_str(label: str, default: Optional[str] = None) -> str:
    if default is not None:
        raw = input(f"{label} [{default}]: ").strip()
        return raw if raw else default
    return input(f"{label}: ").strip()


def prompt_float(
    label: str,
    default: Optional[float] = None,
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
) -> float:
    while True:
        if default is not None:
            raw = input(f"{label} [{default}]: ").strip()
            raw = raw if raw else str(default)
        else:
            raw = input(f"{label}: ").strip()

        try:
            val = float(raw)
        except ValueError:
            print("  ✖ Please enter a valid number.")
            continue

        if min_val is not None and val < min_val:
            print(f"  ✖ Must be >= {min_val}.")
            continue
        if max_val is not None and val > max_val:
            print(f"  ✖ Must be <= {max_val}.")
            continue

        return val


def prompt_int(
    label: str,
    default: Optional[int] = None,
    min_val: Optional[int] = None,
    max_val: Optional[int] = None,
) -> int:
    while True:
        if default is not None:
            raw = input(f"{label} [{default}]: ").strip()
            raw = raw if raw else str(default)
        else:
            raw = input(f"{label}: ").strip()

        try:
            val = int(raw)
        except ValueError:
            print("  ✖ Please enter a valid integer.")
            continue

        if min_val is not None and val < min_val:
            print(f"  ✖ Must be >= {min_val}.")
            continue
        if max_val is not None and val > max_val:
            print(f"  ✖ Must be <= {max_val}.")
            continue

        return val


def choose_length_target() -> int:
    print("\nChoose a length preset or enter a custom number:")
    presets: List[Tuple[str, int]] = list(DEFAULT_LENGTH_PRESETS.items())
    for i, (k, v) in enumerate(presets, start=1):
        print(f"  {i}) {k:14s} -> {v} words")
    print(f"  {len(presets)+1}) custom")

    choice = prompt_int("Select", default=3, min_val=1, max_val=len(presets) + 1)
    if choice == len(presets) + 1:
        return prompt_int("Enter target_word_count", default=5000, min_val=300, max_val=500000)
    return presets[choice - 1][1]


def build_blank_chapters(chapter_count: int, scenes_per_chapter: int) -> List[Dict[str, Any]]:
    chapters: List[Dict[str, Any]] = []
    for ch in range(1, chapter_count + 1):
        chapters.append(
            {
                "chapter": ch,
                "title": f"Chapter {ch}",
                "goal": "",
                "turn": "",
                "consequence": "",
                "must_include": [],
                "pov": "",
                "location": "",
                "scenes": ["" for _ in range(max(1, scenes_per_chapter))],
                "ties_to_key_components": [],
            }
        )
    return chapters


def build_blank_acts(act_count: int, scenes_per_act: int) -> List[Dict[str, Any]]:
    acts: List[Dict[str, Any]] = []
    scene_number = 1
    for a in range(1, act_count + 1):
        scenes: List[str] = []
        for _ in range(scenes_per_act):
            scenes.append(f"Scene {scene_number}: ")
            scene_number += 1
        acts.append({"name": f"Act {a}", "scenes": scenes})
    return acts


def normalize_weights(blend: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ensures weights sum to 1.0. If the user gives nonsense, falls back safely.
    """
    w = []
    for item in blend:
        try:
            wt = float(item.get("weight", 0.0))
        except Exception:
            wt = 0.0
        w.append(max(0.0, wt))

    total = sum(w)
    if total <= 0.0:
        # Safe default: "three_act" full weight
        return [{"style_id": "three_act", "weight": 1.0}]
    out = []
    for item, wt in zip(blend, w):
        out.append({"style_id": str(item.get("style_id", "")).strip() or "three_act", "weight": wt / total})
    return out


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main() -> None:
    print("\n🧱 new_story.py — Story Project Scaffolder")
    print("Creates story_manifest.json in the CURRENT folder.")
    print("Safe by default: does NOT touch novelist.py, Beads, or existing output.\n")

    manifest_path = os.path.join(os.getcwd(), "story_manifest.json")
    if os.path.exists(manifest_path):
        print("⚠ story_manifest.json already exists in this folder.")
        overwrite = prompt_str("Overwrite it? (y/N)", default="N").lower()
        if overwrite != "y":
            print("Aborting.")
            return

    # --- Project identity
    title = prompt_str("Story title", default="Untitled Story")
    slug = slugify(title)
    target_word_count = choose_length_target()

    # --- Style (voice)
    reading_level = prompt_str("Reading level", default="6th Grade")
    tone = prompt_str("Tone", default="Engaging, High-Stakes, Emotional")
    perspective = prompt_str("Perspective", default="Third Person Limited")

    # --- Output strategy (prevents hundreds of files)
    print("\nOutput mode:")
    print("  1) single_file  (recommended: one growing story file, scenes are appended)")
    print("  2) chapter_files (one file per chapter, scenes appended inside)")
    print("  3) scene_files   (one file per scene; legacy/debug)")
    output_choice = prompt_int("Select", default=1, min_val=1, max_val=3)
    output_mode = {1: "single_file", 2: "chapter_files", 3: "scene_files"}[output_choice]

    # Defaults are just conventions; novelist.py can create folders if missing
    output_root = "output"
    story_file = os.path.join(output_root, "draft", "story.md")
    chapter_dir = os.path.join(output_root, "chapters")
    scene_dir = os.path.join(output_root, "scenes")

    # --- Structure planning
    print("\nApproximate structure:")
    chapter_count = prompt_int("Approximate chapter count", default=8, min_val=0, max_val=500)
    scenes_per_chapter = prompt_int("Approx scenes per chapter", default=3, min_val=1, max_val=50)

    # Keep acts for compatibility (even if you mainly think in chapters)
    print("\nSeeding strategy (compatibility + future scaling):")
    print("  1) acts     (classic: seeds one Beads task per act scene)")
    print("  2) chapters (template only unless your novelist supports chapter seeding)")
    print("  3) hybrid   (chapters for planning + acts for seeding tasks)")
    seed_mode_choice = prompt_int("Select", default=3, min_val=1, max_val=3)
    seed_mode = {1: "acts", 2: "chapters", 3: "hybrid"}[seed_mode_choice]

    # For acts scaffolding, pick a sensible default based on chapter count
    default_act_count = 3 if chapter_count >= 9 else 1
    act_count = prompt_int("\nHow many acts (scaffolding; kept for compatibility)?", default=default_act_count, min_val=1, max_val=10)
    scenes_per_act = prompt_int("How many scenes per act (placeholder tasks)?", default=max(3, scenes_per_chapter), min_val=1, max_val=200)

    # If you want a "seed" to kick off Beads immediately, keep at least a few scene placeholders
    min_seed_scenes = prompt_int("\nMinimum seed scenes (guarantee Beads has work to start)", default=3, min_val=1, max_val=200)
    # Ensure acts have at least this many total scene stubs
    total_act_scenes = act_count * scenes_per_act
    if total_act_scenes < min_seed_scenes:
        scenes_per_act = (min_seed_scenes + act_count - 1) // act_count

    # --- Structural guidance blending (STYLES_MASTER)
    print("\nStructural guidance (optional but recommended):")
    print("This expects you to copy styles_master.json into the folder, then set blends here.")
    print("Enter up to 3 style_ids (examples: heros_journey, three_act, freytag, fichtean, pantsing)")
    style_ids: List[str] = []
    weights: List[float] = []
    for idx in range(1, 4):
        sid = prompt_str(f"Style {idx} id (blank to stop)", default="" if idx > 1 else "three_act").strip()
        if not sid:
            break
        wt = prompt_float(f"Style {idx} weight", default=0.34 if idx < 3 else 0.32, min_val=0.0, max_val=1.0)
        style_ids.append(sid)
        weights.append(wt)

    blend = normalize_weights([{"style_id": s, "weight": w} for s, w in zip(style_ids, weights)])
    structure_heat = prompt_float("Structure heat (0=strict, 1=loose)", default=0.6, min_val=0.0, max_val=1.0)

    # --- Opening world state
    opening_time = prompt_str("\nOpening time label", default="Day 1, 08:00 AM")
    opening_location = prompt_str("Opening location", default="")
    protagonist = prompt_str("Protagonist name", default="Jack")
    protagonist_status = prompt_str("Protagonist opening status", default="Tired")
    inventory_csv = prompt_str("Opening inventory (comma-separated)", default="Coffee Mug")
    inventory = [x.strip() for x in inventory_csv.split(",") if x.strip()]

    # --- Manifest
    manifest: Dict[str, Any] = {
        "title": title,
        "slug": slug,
        "target_word_count": target_word_count,

        "manifest_instructions": {
            "created": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "purpose": "Blueprint/config only. The program will not write back to this file.",
            "how_to_start_a_new_story": [
                "1) Copy novelist.py (or novelist_structured.py) and styles_master.json into a new empty folder.",
                "2) Run: python3 new_story.py  (this creates story_manifest.json).",
                "3) Optionally edit story_manifest.json: fill chapters[], key_components[], and acts[].scenes[] with real goals.",
                "4) Run: python3 novelist.py  (it seeds Beads and writes output per output_settings).",
                "5) After tasks are seeded in Beads, avoid editing the seeding list unless you also update Beads tasks manually."
            ],
            "what_the_program_writes": [
                "world_state.json, arc_ledger.json, character_bible.json (living memory/state)",
                "output/ (drafts and compiled story files)",
                ".checkpoints/ (resume mid-scene)",
                ".beads/ (task database, created by bd)"
            ],
            "important_notes": [
                "Acts are kept for compatibility even if you plan with chapters.",
                "Use output_settings.output_mode to avoid hundreds of files.",
                "JSON cannot contain comments; use these instruction blocks instead."
            ],
        },

        "style": {
            "reading_level": reading_level,
            "tone": tone,
            "perspective": perspective,
            "length_reference": LENGTH_REFERENCE,
            "generation_targets": {
                "scene_word_target": 1200,
                "scene_word_min": 800,
                "scene_word_max": 1600,
                "prose_context_scenes": 2,
                "state_excerpt_chars": 4000,
            },
        },

        "output_settings": {
            "output_root": output_root,
            "output_mode": output_mode,  # single_file | chapter_files | scene_files
            "story_file": story_file,
            "chapter_dir": chapter_dir,
            "scene_dir": scene_dir,
            "file_format": "md",  # md or txt
            "append_heading_per_scene": True,
        },

        "structure_guidance": {
            "styles_master_file": "styles_master.json",
            "blend": blend,  # weights normalized to 1.0
            "heat": structure_heat,
            "notes": [
                "blend weights are normalized automatically.",
                "heat is intended as a hint: 0=strict adherence, 1=improv-friendly."
            ],
        },

        "world_state": {
            "current_time": opening_time,
            "current_location": opening_location,
            "inventory": inventory,
            "characters": {
                protagonist: {
                    "status": protagonist_status,
                    "location": opening_location or "Unknown",
                }
            },
        },

        "seed_settings": {
            "seed_mode": seed_mode,
            "min_seed_scenes": min_seed_scenes,
            "future_seed_modes": {
                "acts": "Create one Beads task per acts[].scenes[] (common legacy behavior).",
                "chapters": "Create Chapter + Scene tasks (requires novelist support).",
                "hybrid": "Plan with chapters, but seed tasks from acts (most compatible).",
            },
            "safe_defaults": [
                "Keep acts populated even if you plan to use chapters later.",
                "Do not switch seed_mode mid-project without also updating Beads tasks.",
            ],
        },

        "key_components": [
            {
                "id": "kc-01",
                "name": "Key Component 1",
                "purpose": "",
                "must_be_true_by": "",
                "signals": [],
            }
        ],

        # Planning scaffolding (for YOU). Whether the engine reads this depends on novelist.py.
        "chapters": build_blank_chapters(chapter_count, scenes_per_chapter) if chapter_count > 0 else [
            {
                "chapter": 1,
                "title": "Chapter 1",
                "goal": "",
                "turn": "",
                "consequence": "",
                "must_include": [],
                "pov": "",
                "location": "",
                "scenes": [""],
                "ties_to_key_components": [],
            }
        ],

        # Compatibility scaffolding (for the engine).
        "acts": build_blank_acts(act_count, scenes_per_act),
    }

    # Atomic write
    tmp_path = manifest_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, manifest_path)

    print("\n✅ Created story_manifest.json")
    print(f"   Title:        {title}")
    print(f"   Target words: {target_word_count}")
    print(f"   Seed mode:    {seed_mode} (acts included for compatibility)")
    print(f"   Output mode:  {output_mode}")
    print("\nNext:")
    print("  1) (Optional) Edit acts[].scenes[] with real scene goals (best results).")
    print("  2) (Optional) Fill chapters[] and key_components[] for longer projects.")
    print("  3) Run novelist.py in this folder.\n")


if __name__ == "__main__":
    main()
