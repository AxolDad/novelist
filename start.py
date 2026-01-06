"""
start.py — Novelist System Launcher

Orchestrates the startup of:
1. Core API Server (Background)
2. Streamlit Dashboard (Browser)
3. Novelist Agent (Interactive Console - This Process)

Usage:
  python start.py
"""

import subprocess
import sys
import time
import os
import signal
import webbrowser

def print_banner():
    print("=" * 60)
    print(" 🚀 Launching Novelist System")
    print("=" * 60)

def main():
    print_banner()
    
    processes = []
    
    try:
        # 1. Start Core Server
        print("\n🌍 Starting Core API Server...")
        
        # Kill any zombie process holding port 8000
        try:
            # Find PID using port 8000
            netstat = subprocess.Popen(['netstat', '-ano'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            out, err = netstat.communicate()
            lines = out.decode('latin1').splitlines()
            pid_to_kill = None
            for line in lines:
                if ":8000" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    pid_to_kill = parts[-1]
                    break
            
            if pid_to_kill and pid_to_kill != "0":
                print(f"   ⚠️  Port 8000 occupied by PID {pid_to_kill}. Releasing...")
                subprocess.call(['taskkill', '/F', '/PID', pid_to_kill], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1)
        except Exception as e:
            pass

        server_env = os.environ.copy()
        server_env["LOG_FILENAME"] = "server.log"
        
        # Use Popen to run in background
        server_process = subprocess.Popen(
            [sys.executable, "server.py"],
            env=server_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        processes.append(("Server", server_process))
        
        # Wait for server to be ready (rudimentary check)
        print("   Waiting for server (5s)...")
        time.sleep(5)
        if server_process.poll() is not None:
            print("❌ Server failed to start.")
            out, err = server_process.communicate()
            print(err.decode())
            return
        print("   ✅ Server running (PID: {})".format(server_process.pid))

        # 2. Start Dashboard
        print("\n📊 Starting Dashboard...")
        # streamlit run dashboard.py
        dashboard_process = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "dashboard.py"],
            stdout=subprocess.DEVNULL, # Keep it clean
            stderr=subprocess.DEVNULL
        )
        processes.append(("Dashboard", dashboard_process))
        print("   ✅ Dashboard running (PID: {})".format(dashboard_process.pid))
        
        # 3. Request Manual Agent Start or Run Here?
        # User wants to run the agent in THIS terminal.
        print("\n🤖 PREPARING AGENT...")
        print("   (Ctrl+C to quit and stop all services)")
        print("-" * 60)

        # Smart Project Picker
        import glob
        projects_dir = os.path.abspath("projects")
        available_projects = []
        if os.path.exists(projects_dir):
            for d in os.listdir(projects_dir):
                 full_path = os.path.join(projects_dir, d)
                 if os.path.isdir(full_path):
                     available_projects.append(d)
        
        target_project_arg = []
        
        if available_projects:
            print("\n📚 FOUND PROJECTS:")
            for i, p in enumerate(available_projects):
                print(f"   [{i+1}] {p}")
            print(f"   [N] Create New Story (Launch Dashboard)")
            print(f"   [ENTER] Run default/existing in current dir")
            
            choice = input("\nSelect a project to load [1-{}] or N: ".format(len(available_projects))).strip().lower()
            
            if choice == 'n':
                print("   Opening Dashboard for creation...")
                try:
                    webbrowser.open("http://localhost:8501")
                except: pass
                # Still run agent, it will wait or user can kill it
            elif choice.isdigit() and 1 <= int(choice) <= len(available_projects):
                selected = available_projects[int(choice)-1]
                selected_path = os.path.join(projects_dir, selected)
                print(f"   🚀 Loading: {selected}")
                target_project_arg = ["--project", selected_path]
            else:
                print("   Using default behavior (current directory)...")
        else:
             print("   (No projects found in /projects. Launching in default mode.)")
        
        # Run agent in synchronous subprocess (so we capture input/output here)
        # We pass stdin/stdout/stderr to let user interact directly
        cmd = [sys.executable, "novelist.py"] + target_project_arg
        agent_proc = subprocess.Popen(cmd)
        processes.append(("Agent", agent_proc))
        
        # Wait for agent to finish (or Ctrl+C)
        agent_proc.wait()
        
    except KeyboardInterrupt:
        print("\n\n🛑 Shutdown requested.")
    finally:
        print("\n🧹 Cleaning up services...")
        for name, proc in processes:
            if proc.poll() is None:
                print(f"   Killing {name}...")
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        print("👋 Done.")

if __name__ == "__main__":
    main()
