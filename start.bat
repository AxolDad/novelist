@echo off
setlocal
title Novelist Agent

echo ===================================================
echo 🚀 Launching Novelist System (v2 Launcher)
echo ===================================================

:: Run rotation/migration util if needed
if exist migrate_json_to_sqlite.py (
    if not exist story.db (
        if exist world_state.json (
            echo 📦 Found legacy JSON files. Migrating to SQLite...
            python migrate_json_to_sqlite.py
        )
    )
)

:: Delegate exclusively to Python Launcher
python start.py

:: Pause on exit so errors are visible
if errorlevel 1 pause
