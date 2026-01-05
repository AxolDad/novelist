@echo off
setlocal
title Novelist Agent
echo ===================================================
echo 🚀 Launching Novelist System
echo ===================================================

:: 1. Check for legacy migration
if exist story.db goto :skip_migrate
if exist world_state.json (
    if exist migrate_json_to_sqlite.py (
        echo 📦 Found legacy JSON files. Migrating to SQLite...
        python migrate_json_to_sqlite.py
    )
)
:skip_migrate

:: 2. Launch Dashboard (New Window)
echo 📊 Starting Dashboard (Browser)...
start "Novelist Dashboard" streamlit run dashboard.py

:: 3. Launch Agent (This Window)
echo 🤖 Startup complete. 
echo    - Dashboard is running in the browser.
echo    - Use this window to interact with the Agent.
echo.
python novelist.py

echo.
echo 👋 Agent session ended. Closing.
pause
