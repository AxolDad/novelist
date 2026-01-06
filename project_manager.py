"""
project_manager.py — Project Context Management

Handles project selection, path configuration, and context switching.
"""

import os
import subprocess
import sys
from typing import Dict, Optional, List

import config
from file_utils import safe_read_json
from logger import logger


# Global project path
PROJECT_PATH: Optional[str] = None


def setup_project_paths(project_path: str) -> Dict[str, str]:
    """
    Override global config paths to use project-specific files.
    
    Args:
        project_path: Path to project folder (e.g., "projects/my_novel")
    
    Returns:
        Dict of path names to actual paths
    """
    global PROJECT_PATH
    
    # Normalize path for WSL/Cross-platform compatibility
    project_path = project_path.replace("\\", "/")
    PROJECT_PATH = project_path
    
    # Override all file paths in config module
    config.MANIFEST_FILE = os.path.join(project_path, "story_manifest.json")
    config.STATE_FILE = os.path.join(project_path, "world_state.json")
    config.ARC_FILE = os.path.join(project_path, "arc_ledger.json")
    config.CHAR_BIBLE_FILE = os.path.join(project_path, "character_bible.json")
    config.MACRO_OUTLINE_FILE = os.path.join(project_path, "meta", "macro_outline.json")
    config.PROGRESS_FILE = os.path.join(project_path, "meta", "progress_ledger.json")
    config.OUTPUT_DIR = os.path.join(project_path, "outputs")
    config.SCENES_DIR = os.path.join(project_path, "outputs", "scenes")
    config.MANUSCRIPT_FILE_DEFAULT = os.path.join(project_path, "outputs", "manuscript.md")
    
    # Ensure directories exist
    os.makedirs(os.path.join(project_path, "meta", "checkpoints"), exist_ok=True)
    os.makedirs(config.SCENES_DIR, exist_ok=True)
    
    return {
        "manifest": config.MANIFEST_FILE,
        "world_state": config.STATE_FILE,
        "manuscript": config.MANUSCRIPT_FILE_DEFAULT,
    }


def scan_available_projects(projects_dir: str = "projects") -> List[str]:
    """
    Scan for available projects in the projects directory.
    
    Returns:
        List of project directory names with valid manifests
    """
    projects_dir = os.path.abspath(projects_dir)
    available = []
    
    if os.path.exists(projects_dir):
        for d in os.listdir(projects_dir):
            full_path = os.path.join(projects_dir, d)
            manifest_path = os.path.join(full_path, "story_manifest.json")
            if os.path.isdir(full_path) and os.path.exists(manifest_path):
                available.append(d)
    
    return available


def run_project_picker() -> Optional[str]:
    """
    Interactive project picker for when no project is specified.
    
    Returns:
        Selected project path, or None if user quits
    """
    projects_dir = os.path.abspath("projects")
    available_projects = scan_available_projects(projects_dir)
    
    if not available_projects:
        print(f"⚠️  No Story Manifest found in current folder.")
        print(f"   (No projects found in {projects_dir})")
        print("\n   Run 'streamlit run dashboard.py' to create a New Story.")
        input("   Press Enter to exit...")
        return None
    
    print("\n📚 Available Projects:")
    for i, p in enumerate(available_projects):
        print(f"   [{i+1}] {p}")
    print(f"   [N] Create New (Launch Dashboard)")
    print(f"   [Q] Quit")
    
    choice = input("\nSelect a project to load: ").strip().lower()
    
    if choice == 'n':
        print("🚀 Launching Dashboard for Project Creation...")
        try:
            subprocess.Popen(["streamlit", "run", "dashboard.py"], shell=True)
        except Exception as e:
            print(f"Error launching dashboard: {e}")
        return None
    elif choice == 'q':
        return None
    elif choice.isdigit() and 1 <= int(choice) <= len(available_projects):
        selected = available_projects[int(choice)-1]
        return os.path.join(projects_dir, selected)
    else:
        print("❌ Invalid selection.")
        return None


def handle_project_argument(project_arg: Optional[str]) -> bool:
    """
    Handle --project CLI argument.
    
    Returns:
        True if project was set up successfully, False otherwise
    """
    if not project_arg:
        return False
        
    project_path = os.path.abspath(project_arg)
    if os.path.exists(project_path):
        logger.info(f"Switching context to: {project_path}")
        os.chdir(project_path)
        setup_project_paths(project_path)
        if os.path.exists("story.db"):
            logger.info("Found story.db")
        return True
    else:
        logger.error(f"Project path not found: {project_path}")
        return False
