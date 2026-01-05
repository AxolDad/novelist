"""
dashboard.py — Streamlit Dashboard for Novelist System

Web-based UI for configuring stories, monitoring progress, and viewing logs.
Run with: streamlit run dashboard.py
"""

import streamlit as st
import json
import os
import subprocess
import time
import yaml
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

# Import from existing modules
from config import (
    MANIFEST_FILE, STATE_FILE, ARC_FILE, CHAR_BIBLE_FILE,
    STYLES_MASTER_FILE, MANUSCRIPT_FILE_DEFAULT, OUTPUT_DIR,
    WRITER_MODEL, CRITIC_MODEL, LLM_PROVIDER, MODEL_PRESETS,
)
from file_utils import safe_read_json, safe_write_json
from ollama_client import check_ollama_connection
from state_manager import compute_current_word_count, get_target_word_count
from prompts import load_styles_master
import sqlite3
import db_manager

def get_db_data(project_path):
    """Fetch all state from SQLite."""
    db_path = os.path.join(project_path, "story.db")
    if not os.path.exists(db_path):
        return {}, {}, {}
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # KV
        kv = {}
        try:
            rows = conn.execute("SELECT key, value FROM kv_store").fetchall()
            for r in rows: kv[r["key"]] = json.loads(r["value"])
        except: pass
        
        # Chars
        chars = {}
        try:
            rows = conn.execute("SELECT * FROM characters").fetchall()
            for r in rows:
                # Handle our specific hack where voice_notes stores the dict profile
                profile = {}
                if r["voice_notes"] and r["voice_notes"].startswith("{"):
                    profile = json.loads(r["voice_notes"])
                    
                chars[r["name"]] = {
                    "role": r["role"],
                    "description": r["description"],
                    "voice_notes": profile.get("voice_notes", []),
                    "behavioral_markers": profile.get("behavioral_markers", []),
                    "hard_limits": profile.get("hard_limits", []),
                    "relationships": json.loads(r["relationships"] or "{}"),
                    "current_status": json.loads(r["current_status"] or "{}")
                }
        except: pass
        
        # Arc
        arc = {"stakes": [], "promises_to_reader": [], "unresolved_questions": [], "scene_history": []}
        try:
            rows = conn.execute("SELECT type, description FROM arc_items WHERE status='active'").fetchall()
            for r in rows:
                if r["type"] == "stake": arc["stakes"].append(r["description"])
                elif r["type"] == "promise": arc["promises_to_reader"].append(r["description"])
                elif r["type"] == "question": arc["unresolved_questions"].append(r["description"])
                
            rows = conn.execute("SELECT * FROM scenes ORDER BY id DESC LIMIT 5").fetchall()
            for r in rows:
                arc["scene_history"].append({
                    "title": r["title"],
                    "summary": r["summary"],
                    "consequence": r["consequence"],
                    "scores": json.loads(r["tribunal_scores"] or "{}")
                })
            arc["scene_history"].reverse()
        except: pass
        
        conn.close()
        return kv, chars, arc
    except Exception as e:
        return {}, {}, {}

# Page config
st.set_page_config(
    page_title="Novelist Dashboard",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .stProgress > div > div > div > div { background-color: #4CAF50; }
    .metric-card { 
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem; border-radius: 0.5rem; color: white;
    }
    .status-ok { color: #4CAF50; font-weight: bold; }
    .status-error { color: #f44336; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# STORY PROFILE PARSER
# =============================================================================
def parse_story_profile(content: str) -> Dict[str, Any]:
    """Parse Markdown with YAML frontmatter into manifest format."""
    # Extract YAML frontmatter between --- markers
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not frontmatter_match:
        return {}
    
    try:
        data = yaml.safe_load(frontmatter_match.group(1))
    except yaml.YAMLError as e:
        st.error(f"YAML parsing error: {e}")
        return {}
    
    # Convert to manifest format
    manifest = {}
    
    # Direct mappings
    for key in ['title', 'genre', 'synopsis', 'target_word_count']:
        if key in data:
            manifest[key] = data[key]
    
    # Style section
    if 'style' in data:
        manifest['style'] = data['style']
    
    # Planning section
    if 'planning' in data:
        manifest['planning'] = data['planning']
    
    # Characters -> world_state.characters
    world_state = {}
    if 'characters' in data:
        world_state['characters'] = {}
        for char in data['characters']:
            name = char.get('name', 'Unknown')
            world_state['characters'][name] = {
                'role': char.get('role', ''),
                'arc': char.get('arc', ''),
                'backstory': char.get('backstory', ''),
                'traits': char.get('traits', []),
                'voice': char.get('voice', ''),
            }
    
    # World section
    if 'world' in data:
        world_state.update(data['world'])
    
    # Acts section
    if 'acts' in data:
        manifest['acts'] = []
        for act in data['acts']:
            act_data = {'name': act.get('name', ''), 'scenes': []}
            for chapter in act.get('chapters', []):
                for scene in chapter.get('scenes', []):
                    act_data['scenes'].append(scene)
            manifest['acts'].append(act_data)
    
    return {'manifest': manifest, 'world_state': world_state}


# =============================================================================
# NEW PROJECT CREATION
# =============================================================================
def create_new_project(project_name: str, project_dir: str = "projects") -> Dict[str, Any]:
    """
    Create a new story project with organized folder structure.
    
    Args:
        project_name: Name of the new story/project
        project_dir: Parent directory for all projects
    
    Returns: Dict with project info and paths
    """
    import shutil
    
    # Sanitize project name for folder
    safe_name = re.sub(r'[^\w\s-]', '', project_name).strip().replace(' ', '_').lower()
    project_path = os.path.join(project_dir, safe_name)
    
    # Create project structure
    folders = [
        project_path,
        os.path.join(project_path, "meta"),
        os.path.join(project_path, "meta", "checkpoints"),
        os.path.join(project_path, "outputs"),
        os.path.join(project_path, "outputs", "scenes"),
        os.path.join(project_path, "planning"),
        os.path.join(project_path, "exports"),
    ]
    
    for folder in folders:
        os.makedirs(folder, exist_ok=True)
    
    # Create initial files
    manifest = {
        "title": project_name,
        "genre": "",
        "synopsis": "",
        "target_word_count": 90000,
        "style": {
            "activation_key": "(immersive fiction)",
            "tone": "",
            "pov": "third_limited",
            "theme": "",
            "voice_notes": []
        },
        "planning": {
            "scene_word_target": 1200,
            "structure_heat": 0.25,
            "structure_blend": []
        },
        "output": {
            "mode": "manuscript",
            "manuscript_file": os.path.join(project_path, "outputs", "manuscript.md"),
            "write_scene_files": True
        }
    }
    
    world_state = {
        "current_time": "",
        "current_location": "",
        "weather": "",
        "inventory": [],
        "characters": {}
    }
    
    # Write files
    files = {
        os.path.join(project_path, "story_manifest.json"): manifest,
        os.path.join(project_path, "meta", "progress_ledger.json"): {"next_scene_index": 1},
    }
    
    for filepath, content in files.items():
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(content, f, indent=2)

    # Initialize SQLite DB
    project_db = os.path.join(project_path, "story.db")
    db_manager.init_db(project_db)
    
    # Seed default state
    try:
        with sqlite3.connect(project_db) as conn:
            conn.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", ("current_time", json.dumps("")))
            conn.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", ("current_location", json.dumps("")))
            conn.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", ("inventory", json.dumps([])))
            conn.commit()
    except Exception as e:
        print(f"Error seeding DB: {e}")
    
    # Copy story profile template if available
    template_path = os.path.join("templates", "story_profile_template.md")
    if os.path.exists(template_path):
        shutil.copy(template_path, os.path.join(project_path, "story_profile.md"))
    
    return {
        "name": project_name,
        "safe_name": safe_name,
        "path": project_path,
        "manifest_path": os.path.join(project_path, "story_manifest.json"),
        "folders": folders
    }


def list_projects(project_dir: str = "projects") -> List[Dict[str, Any]]:
    """List all existing projects."""
    projects = []
    if os.path.exists(project_dir):
        for name in os.listdir(project_dir):
            project_path = os.path.join(project_dir, name)
            if os.path.isdir(project_path):
                manifest_path = os.path.join(project_path, "story_manifest.json")
                manifest = safe_read_json(manifest_path, {})
                projects.append({
                    "name": manifest.get("title", name),
                    "folder": name,
                    "path": project_path,
                    "word_count": compute_current_word_count(
                        manifest, 
                        os.path.join(project_path, "outputs", "manuscript.md")
                    ) if manifest else 0
                })
    return projects


def get_active_project_paths() -> Dict[str, str]:
    """
    Get file paths for the active project.
    Returns paths to non-existent files if no project is active (prevents ghost data).
    """
    active_project = st.session_state.get('active_project_path', None)
    
    if active_project and os.path.exists(active_project):
        return {
            "manifest": os.path.join(active_project, "story_manifest.json"),
            "world_state": os.path.join(active_project, "world_state.json"),
            "arc_ledger": os.path.join(active_project, "arc_ledger.json"),
            "char_bible": os.path.join(active_project, "character_bible.json"),
            "manuscript": os.path.join(active_project, "outputs", "manuscript.md"),
            "project_path": active_project,
            "db": os.path.join(active_project, "story.db")
        }
    else:
        # Return paths to non-existent temp location so no ghost data is read
        return {
            "manifest": ".no_project/story_manifest.json",
            "world_state": ".no_project/world_state.json",
            "arc_ledger": ".no_project/arc_ledger.json",
            "char_bible": ".no_project/character_bible.json",
            "manuscript": ".no_project/manuscript.md",
            "project_path": "",
        }


def set_active_project(project_path: str):
    """Set the active project in session state and persist it."""
    st.session_state['active_project_path'] = project_path
    try:
        with open(".last_active_project", "w") as f:
            f.write(project_path)
    except Exception:
        pass


def load_last_active_project():
    """Load the last active project from persistence if not already in session."""
    if 'active_project_path' not in st.session_state:
        if os.path.exists(".last_active_project"):
            try:
                with open(".last_active_project", "r") as f:
                    path = f.read().strip()
                if os.path.exists(path):
                    st.session_state['active_project_path'] = path
            except Exception:
                pass


# =============================================================================
# SIDEBAR NAVIGATION
# =============================================================================
def sidebar():
    """Render sidebar navigation with Director's Dashboard engine selector."""
    st.sidebar.title("📚 Novelist")
    st.sidebar.markdown("---")
    
    page = st.sidebar.radio(
        "Navigation",
        ["🏠 Home", "📖 Story Setup", "🎨 Styles", "📊 Monitor", "📋 Logs"],
        label_visibility="collapsed"
    )
    
    st.sidebar.markdown("---")
    
    # ===========================================
    # DIRECTOR'S DASHBOARD - Engine Selection
    # ===========================================
    st.sidebar.subheader("🧠 Neural Engine")
    
    engine_options = {
        "architect": MODEL_PRESETS["architect"]["name"],
        "artist": MODEL_PRESETS["artist"]["name"]
    }
    
    # Get current selection from session state
    current_engine = st.session_state.get('selected_engine', 'architect')
    
    selected_engine = st.sidebar.radio(
        "Select Workflow:",
        list(engine_options.keys()),
        format_func=lambda x: engine_options[x],
        index=0 if current_engine == 'architect' else 1,
        label_visibility="collapsed"
    )
    
    # Store selection
    st.session_state['selected_engine'] = selected_engine
    preset = MODEL_PRESETS[selected_engine]
    
    # Display engine info
    if selected_engine == "architect":
        st.sidebar.info(f"🔧 {preset['model'].split('/')[-1]}")
    else:
        st.sidebar.warning(f"🎨 {preset['model'].split('/')[-1]}")
    
    st.sidebar.caption(preset['description'])
    
    # Show parameters in expander
    with st.sidebar.expander("⚙️ Active Parameters"):
        params = preset['parameters']
        st.markdown(f"**Temperature:** {params.get('temperature', 'N/A')}")
        st.markdown(f"**Rep Penalty:** {params.get('repetition_penalty', 'N/A')}")
        st.markdown(f"**Top P:** {params.get('top_p', 'N/A')}")
        if 'smoothing_factor' in params:
            st.markdown(f"**Smoothing:** {params['smoothing_factor']}")
        if 'min_p' in params:
            st.markdown(f"**Min P:** {params['min_p']}")
        st.markdown(f"**Max Tokens:** {params.get('max_tokens', 'N/A')}")
    
    # MASTERSTORY toggle for Artist
    if selected_engine == "artist":
        masterstory = st.sidebar.checkbox(
            "🎭 Inject [MASTERSTORY] Skills", 
            value=st.session_state.get('masterstory_enabled', True)
        )
        st.session_state['masterstory_enabled'] = masterstory
    
    st.sidebar.markdown("---")
    
    # Auto-refresh controls
    st.sidebar.subheader("🔄 Auto-Refresh")
    auto_refresh = st.sidebar.checkbox("Enable auto-refresh", value=st.session_state.get('auto_refresh', False))
    refresh_interval = st.sidebar.slider(
        "Interval (seconds)", 
        min_value=5, max_value=60, 
        value=st.session_state.get('refresh_interval', 10),
        disabled=not auto_refresh
    )
    
    # Store in session state
    st.session_state['auto_refresh'] = auto_refresh
    st.session_state['refresh_interval'] = refresh_interval
    
    # Trigger auto-refresh if enabled
    if auto_refresh:
        st.sidebar.caption(f"Refreshing every {refresh_interval}s...")
        time.sleep(refresh_interval)
        st.rerun()
    
    st.sidebar.markdown("---")
    
    # Quick status
    ollama_ok = check_ollama_connection()
    status_icon = "🟢" if ollama_ok else "🔴"
    st.sidebar.markdown(f"**LLM Status:** {status_icon} {LLM_PROVIDER.upper()}")
    st.sidebar.caption(f"Writer: `{WRITER_MODEL}`")
    st.sidebar.caption(f"Critic: `{CRITIC_MODEL}`")
    
    return page


# =============================================================================
# HOME PAGE
# =============================================================================
def page_home():
    """Home page with system status and quick stats."""
    st.title("🏠 Novelist Dashboard")
    st.markdown("AI-powered novel writing system")
    
    # Get active project paths
    paths = get_active_project_paths()
    
    col1, col2, col3 = st.columns(3)
    
    # Load manifest from active project
    manifest = safe_read_json(paths["manifest"], {})
    title = manifest.get("title", "(No story loaded)")
    
    # Show active project indicator
    active_project = st.session_state.get('active_project_path', None)
    if active_project:
        project_name = os.path.basename(active_project)
        st.caption(f"📂 Active Project: `{project_name}`")
    
    with col1:
        st.metric("📘 Current Story", title)
    
    with col2:
        target = get_target_word_count(manifest)
        current = compute_current_word_count(manifest, paths["manuscript"])
        pct = int((current / target * 100)) if target > 0 else 0
        st.metric("✍️ Word Count", f"{current:,} / {target:,}", f"{pct}%")
    
    with col3:
        ollama_ok = check_ollama_connection()
        status = "Connected" if ollama_ok else "Offline"
        st.metric("🔌 LLM Status", status)
    
    st.markdown("---")
    
    # Progress bar
    if target > 0:
        st.subheader("📈 Progress")
        progress = min(current / target, 1.0)
        st.progress(progress, text=f"{pct}% complete ({current:,} words)")
    
    # Quick actions
    st.markdown("---")
    st.subheader("⚡ Quick Actions")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("▶️ Start Agent", use_container_width=True):
            st.session_state['agent_running'] = True
            st.info("Agent started! Check Logs page for output.")
    
    with col2:
        if st.button("📄 View Manuscript", use_container_width=True):
            if os.path.exists(paths["manuscript"]):
                with open(paths["manuscript"], 'r', encoding='utf-8') as f:
                    st.session_state['manuscript_preview'] = f.read()
    
    with col3:
        if st.button("🔄 Refresh Status", use_container_width=True):
            st.rerun()
    
    with col4:
        if st.button("⚙️ Edit .env", use_container_width=True):
            st.info("Edit .env file in your editor to change model settings.")
    
    # ===========================================
    # NEW STORY / PROJECT BROWSER
    # ===========================================
    st.markdown("---")
    st.subheader("📁 Story Projects")
    
    tab_new, tab_existing = st.tabs(["✨ New Story", "📚 Existing Projects"])
    
    with tab_new:
        st.markdown("Create a new story project with organized folder structure.")
        
        new_project_name = st.text_input("Story Title", placeholder="e.g., The Midnight Garden")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption("Creates: story_manifest.json, world_state.json, arc_ledger.json, and organized folders")
        with col2:
            if st.button("🚀 Create Project", type="primary", use_container_width=True, disabled=not new_project_name):
                if new_project_name:
                    result = create_new_project(new_project_name)
                    set_active_project(result['path'])  # Switch to new project
                    st.success(f"✅ Created project: **{result['name']}**")
                    st.caption(f"📂 Location: `{result['path']}`")
                    st.balloons()
                    st.rerun()  # Refresh to show new project stats
    
    with tab_existing:
        projects = list_projects()
        
        if projects:
            for project in projects:
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    # Indicate if this is the active project
                    is_active = st.session_state.get('active_project_path') == project['path']
                    active_marker = " ✅" if is_active else ""
                    st.markdown(f"**{project['name']}**{active_marker}")
                    st.caption(f"📂 {project['folder']} • {project['word_count']:,} words")
                with col2:
                    if st.button("📖 Open", key=f"open_{project['folder']}", use_container_width=True):
                        set_active_project(project['path'])
                        st.rerun()
                with col3:
                    st.button("🗑️", key=f"del_{project['folder']}", use_container_width=True)
        else:
            st.info("No projects yet. Create your first story above!")
    
    # Manuscript preview
    if 'manuscript_preview' in st.session_state:
        st.markdown("---")
        st.subheader("📄 Manuscript Preview")
        st.text_area("manuscript_preview_area", st.session_state['manuscript_preview'], height=400, label_visibility="collapsed")


# =============================================================================
# STORY SETUP PAGE
# =============================================================================
def page_story_setup():
    """Story setup wizard."""
    st.title("📖 Story Setup")
    
    # Get active project paths
    paths = get_active_project_paths()
    
    # Load existing manifest from active project
    manifest = safe_read_json(paths["manifest"], {})
    
    tab1, tab2, tab3, tab4 = st.tabs(["📝 Basic Info", "👥 Characters", "🎬 Acts & Scenes", "📤 Upload Profile"])
    
    with tab4:
        st.subheader("📤 Upload Story Profile")
        st.markdown("""
        Upload a Markdown file with YAML frontmatter to configure your entire story at once.
        Download the template below to get started.
        """)
        
        # Download template button
        template_path = os.path.join("templates", "story_profile_template.md")
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            st.download_button(
                "📥 Download Template",
                template_content,
                file_name="story_profile_template.md",
                mime="text/markdown",
                use_container_width=True
            )
        
        st.markdown("---")
        
        # File uploader
        uploaded_file = st.file_uploader(
            "Upload your story profile (.md)", 
            type=['md', 'markdown', 'txt'],
            help="Markdown file with YAML frontmatter"
        )
        
        if uploaded_file is not None:
            content = uploaded_file.read().decode('utf-8')
            
            # Preview the content
            with st.expander("📄 Preview uploaded file"):
                st.code(content[:2000] + ("..." if len(content) > 2000 else ""), language="yaml")
            
            # Parse and import
            if st.button("🚀 Import Story Profile", type="primary", use_container_width=True):
                # Check if a project is active FIRST
                if not paths.get("project_path") or not os.path.exists(paths.get("project_path", "")):
                    st.error("❌ No active project! Please create a project first using 'New Story' tab below.")
                    st.stop()
                
                result = parse_story_profile(content)
                
                if result:
                    parsed_manifest = result.get('manifest', {})
                    parsed_world = result.get('world_state', {})
                    
                    # Merge with existing manifest and write to ACTIVE PROJECT (not root!)
                    manifest.update(parsed_manifest)
                    safe_write_json(paths["manifest"], manifest)
                    
                    # Update world state if we have character/world data
                    if parsed_world:
                        existing_world = safe_read_json(paths["world_state"], {})
                        existing_world.update(parsed_world)
                        safe_write_json(paths["world_state"], existing_world)
                    
                    st.success(f"✅ Imported story profile: **{manifest.get('title', 'Untitled')}**")
                    st.info(f"📂 Saved to: `{paths['project_path']}`")
                    st.info(f"🎯 Target word count: {manifest.get('target_word_count', 'Not set')}")
                    st.balloons()
                    
                    # Show what was imported
                    with st.expander("📊 Import Summary"):
                        st.json({
                            'title': manifest.get('title'),
                            'genre': manifest.get('genre'),
                            'target_word_count': manifest.get('target_word_count'),
                            'characters_imported': list(parsed_world.get('characters', {}).keys()),
                            'acts_imported': len(manifest.get('acts', []))
                        })
                    
                    # Rerun to refresh UI with new values
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("❌ Failed to parse story profile. Check YAML syntax.")
    
    with tab1:
        st.subheader("Story Details")
        
        title = st.text_input("Title", manifest.get("title", ""))
        synopsis = st.text_area("Synopsis", manifest.get("synopsis", ""), height=100)
        genre = st.text_input("Genre", manifest.get("genre", ""))
        
        col1, col2 = st.columns(2)
        with col1:
            target_wc = st.number_input(
                "Target Word Count", 
                min_value=1000, max_value=500000, 
                value=manifest.get("target_word_count", 90000),
                step=1000
            )
        with col2:
            scene_target = st.number_input(
                "Scene Word Target",
                min_value=500, max_value=5000,
                value=(manifest.get("planning", {}) or {}).get("scene_word_target", 1200),
                step=100
            )
        
        # Style settings
        st.subheader("Style Settings")
        style = manifest.get("style", {}) or {}
        
        tone = st.text_input("Tone", style.get("tone", ""))
        pov = st.selectbox("Point of View", ["first_person", "third_limited", "third_omniscient"], 
                          index=["first_person", "third_limited", "third_omniscient"].index(style.get("pov", "third_limited")))
        theme = st.text_input("Theme", style.get("theme", ""))
        
        if st.button("💾 Save Story Details", type="primary"):
            manifest["title"] = title
            manifest["synopsis"] = synopsis
            manifest["genre"] = genre
            manifest["target_word_count"] = target_wc
            manifest.setdefault("planning", {})["scene_word_target"] = scene_target
            manifest.setdefault("style", {}).update({
                "tone": tone,
                "pov": pov,
                "theme": theme
            })
            safe_write_json(paths["manifest"], manifest)
            st.success("✅ Story details saved!")
    
    with tab2:
        st.subheader("Characters")
        
        world_state = safe_read_json(paths["world_state"], {})
        characters = world_state.get("characters", {})
        
        # Display existing characters
        if characters:
            for name, info in characters.items():
                with st.expander(f"👤 {name}"):
                    status = st.text_input(f"Status ({name})", info.get("status", ""), key=f"char_status_{name}")
                    location = st.text_input(f"Location ({name})", info.get("location", ""), key=f"char_loc_{name}")
                    if st.button(f"Update {name}", key=f"update_{name}"):
                        world_state["characters"][name]["status"] = status
                        world_state["characters"][name]["location"] = location
                        safe_write_json(STATE_FILE, world_state)
                        st.success(f"Updated {name}")
        
        # Add new character
        st.markdown("---")
        st.subheader("➕ Add Character")
        new_name = st.text_input("Character Name")
        new_status = st.text_input("Initial Status")
        new_location = st.text_input("Starting Location")
        
        if st.button("Add Character"):
            if new_name:
                world_state.setdefault("characters", {})[new_name] = {
                    "status": new_status,
                    "location": new_location
                }
                safe_write_json(STATE_FILE, world_state)
                st.success(f"Added {new_name}!")
                st.rerun()
    
    with tab3:
        st.subheader("Acts & Scenes")
        
        acts = manifest.get("acts", [])
        
        if acts:
            for i, act in enumerate(acts):
                with st.expander(f"🎭 Act {i+1}"):
                    scenes = act.get("scenes", [])
                    for j, scene in enumerate(scenes):
                        st.text(f"Scene {j+1}: {scene[:80]}...")
        else:
            st.info("No acts defined yet. Add scenes below or let the agent auto-generate them.")
        
        # Add scene
        st.markdown("---")
        st.subheader("➕ Add Scene")
        act_num = st.number_input("Act Number", min_value=1, value=1)
        scene_desc = st.text_area("Scene Description/Goal")
        
        if st.button("Add Scene"):
            if scene_desc:
                while len(manifest.setdefault("acts", [])) < act_num:
                    manifest["acts"].append({"scenes": []})
                manifest["acts"][act_num - 1].setdefault("scenes", []).append(scene_desc)
                safe_write_json(MANIFEST_FILE, manifest)
                st.success("Scene added!")
                st.rerun()


# =============================================================================
# STYLES PAGE
# =============================================================================
def page_styles():
    """Style configuration with visual sliders."""
    st.title("🎨 Structure & Style")
    
    manifest = safe_read_json(MANIFEST_FILE, {})
    styles_master = load_styles_master()
    available_styles = styles_master.get("styles", {})
    
    planning = manifest.get("planning", {}) or {}
    current_blend = planning.get("structure_blend", [])
    current_heat = planning.get("structure_heat", 0.25)
    
    # Heat/Autonomy slider
    st.subheader("🌡️ Structure Heat (Autonomy)")
    heat = st.slider(
        "0 = Strict adherence to beats, 1 = High creative autonomy",
        min_value=0.0, max_value=1.0, value=float(current_heat), step=0.05
    )
    
    st.markdown("---")
    
    # Structure blend
    st.subheader("📐 Structure Blend")
    st.caption("Select structures and adjust weights. Weights should sum to 100%.")
    
    # Show available styles
    style_names = list(available_styles.keys())
    
    # Initialize blend in session state
    if 'blend' not in st.session_state:
        st.session_state['blend'] = {item['style']: item['weight'] for item in current_blend} if current_blend else {}
    
    # Filter blend to only include valid styles (prevents error when styles_master changes)
    valid_blend_keys = [k for k in st.session_state['blend'].keys() if k in style_names]
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        selected_styles = st.multiselect(
            "Select Structures",
            style_names,
            default=valid_blend_keys,  # Only use valid keys as defaults
            format_func=lambda x: available_styles.get(x, {}).get("label", x)
        )
    
    # Weight sliders for selected styles
    new_blend = {}
    if selected_styles:
        st.markdown("**Adjust Weights:**")
        cols = st.columns(len(selected_styles))
        for i, style_key in enumerate(selected_styles):
            with cols[i]:
                style_info = available_styles.get(style_key, {})
                label = style_info.get("label", style_key)
                current_weight = st.session_state['blend'].get(style_key, 1.0 / len(selected_styles))
                weight = st.slider(
                    label,
                    min_value=0.0, max_value=1.0,
                    value=float(current_weight),
                    step=0.05,
                    key=f"weight_{style_key}"
                )
                new_blend[style_key] = weight
        
        # Show total
        total = sum(new_blend.values())
        if abs(total - 1.0) > 0.01:
            st.warning(f"⚠️ Weights sum to {total*100:.0f}%. Should be 100%.")
        else:
            st.success(f"✅ Weights sum to {total*100:.0f}%")
    
    # Style previews
    st.markdown("---")
    st.subheader("📖 Style Reference")
    
    for style_key in selected_styles:
        style_info = available_styles.get(style_key, {})
        with st.expander(f"📋 {style_info.get('label', style_key)}"):
            st.markdown(f"**Beats:** {', '.join(style_info.get('beats', []))}")
            st.markdown(f"**Notes:** {style_info.get('notes', 'N/A')}")
    
    # Save button
    st.markdown("---")
    if st.button("💾 Save Style Configuration", type="primary"):
        blend_list = [{"style": k, "weight": v} for k, v in new_blend.items()]
        manifest.setdefault("planning", {})["structure_blend"] = blend_list
        manifest["planning"]["structure_heat"] = heat
        safe_write_json(MANIFEST_FILE, manifest)
        st.session_state['blend'] = new_blend
        st.success("✅ Style configuration saved!")


# =============================================================================
# MONITOR PAGE
# =============================================================================
def page_monitor():
    """Progress monitoring and state viewer."""
    st.title("📊 Monitor")
    
    # Get active project paths
    paths = get_active_project_paths()
    
    manifest = safe_read_json(paths["manifest"], {})
    
    # Progress section
    st.subheader("📈 Progress")
    
    target = get_target_word_count(manifest)
    current = compute_current_word_count(manifest, paths["manuscript"])
    pct = (current / target * 100) if target > 0 else 0
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Current Words", f"{current:,}")
    with col2:
        st.metric("Target Words", f"{target:,}")
    with col3:
        st.metric("Progress", f"{pct:.1f}%")
    
    st.progress(min(pct / 100, 1.0))
    
    st.markdown("---")
    
    # State viewers
    # State viewers
    st.subheader("📁 State Files (SQLite Backed)")
    
    world_state, char_bible, arc_ledger = get_db_data(paths["project_path"])
    
    tab1, tab2, tab3, tab4 = st.tabs(["🌍 World State", "📊 Arc Ledger", "👥 Character Bible", "📋 Manifest"])
    
    with tab1:
        st.json(world_state)
    
    with tab2:
        st.json(arc_ledger)
    
    with tab3:
        st.json(char_bible)
    
    with tab4:
        st.json(manifest)
    
    # Tribunal history
    st.markdown("---")
    st.subheader("🏛️ Recent Tribunal Scores")
    
    scene_history = arc_ledger.get("scene_history", [])
    
    if scene_history:
        for scene in scene_history[-5:]:
            scores = scene.get("scores", {})
            score_txt = " | ".join([f"{k}: {v}" for k, v in scores.items()])
            st.markdown(f"**{scene.get('title', 'Scene')}**: {scene.get('consequence', 'N/A')} _({score_txt})_")
    else:
        st.info("No scene history yet.")


# =============================================================================
# LOGS PAGE
# =============================================================================
def page_logs():
    """Log viewer and agent controls."""
    st.title("📋 Logs & Control")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🎮 Agent Control")
        
        if st.button("▶️ Start Novelist Agent", use_container_width=True, type="primary"):
            st.info("Starting agent... Output will appear in terminal.")
            
            # Get the current working directory for the command
            cwd = os.path.abspath(".").replace("\\", "/")
            active_project = st.session_state.get('active_project_path', None)
            
            st.warning("⚠️ Streamlit doesn't support long-running sub-processes well. Run this in a **Terminal**:")
            
            # Show one-liner that can be copy-pasted
            python_cmd = "python3" # Default to python3 for WSL/Linux which is likely where the user is
            if active_project:
                # Normalize active project path too
                active_project = active_project.replace("\\", "/")
                cmd = f'cd "{cwd}" && {python_cmd} novelist.py --project "{active_project}"'
            else:
                cmd = f'cd "{cwd}" && {python_cmd} novelist.py'
            
            st.code(cmd, language="bash")
            st.caption(f"📂 Working directory: `{cwd}`")
        
        if st.button("⏹️ Stop Agent", use_container_width=True):
            st.warning("To stop, use **Ctrl+C** in the terminal running novelist.py")
    
    with col2:
        st.subheader("📂 Checkpoints")
        
        checkpoint_dir = os.path.join("meta", "checkpoints")
        if os.path.exists(checkpoint_dir):
            checkpoints = os.listdir(checkpoint_dir)
            if checkpoints:
                for cp in checkpoints:
                    st.text(f"📄 {cp}")
            else:
                st.info("No checkpoints found.")
        else:
            st.info("Checkpoint directory not found.")
    
    st.markdown("---")
    
    # Log file viewer
    st.subheader("📜 Log Output")
    
    log_file = os.path.join("logs", "novelist.log")
    
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Show last 50 lines
        st.text_area("Recent Logs", "".join(lines[-50:]), height=400)
        
        if st.button("🔄 Refresh Logs"):
            st.rerun()
    else:
        st.info("No log file found. Logs will appear here after running the agent.")
        st.caption(f"Expected location: {log_file}")
    
    # Manual state reset
    st.markdown("---")
    st.subheader("⚠️ Danger Zone")
    
    with st.expander("Reset Options"):
        if st.button("🗑️ Clear All Checkpoints", type="secondary"):
            checkpoint_dir = os.path.join("meta", "checkpoints")
            if os.path.exists(checkpoint_dir):
                for f in os.listdir(checkpoint_dir):
                    os.remove(os.path.join(checkpoint_dir, f))
                st.success("Checkpoints cleared.")
        
        st.warning("These actions cannot be undone!")


# =============================================================================
# MAIN APP
# =============================================================================
def main():
    """Main app entry point."""
    load_last_active_project()
    page = sidebar()
    
    if page == "🏠 Home":
        page_home()
    elif page == "📖 Story Setup":
        page_story_setup()
    elif page == "🎨 Styles":
        page_styles()
    elif page == "📊 Monitor":
        page_monitor()
    elif page == "📋 Logs":
        page_logs()


if __name__ == "__main__":
    main()
