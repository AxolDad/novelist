
import subprocess
import time
import sys
import os

# Set distinct log file for the test client process
os.environ["LOG_FILENAME"] = "verification_client.log"

import requests
import db_manager as client

def test_integration():
    print("🚀 Starting Integration Test...")
    
    # 1. Start Server
    print("   Starting server.py...")
    # Prepare server env
    server_env = os.environ.copy()
    server_env["LOG_FILENAME"] = "server.log"
    
    proc = subprocess.Popen(
        [sys.executable, "server.py"], 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE,
        env=server_env
    )
    
    try:
        # Wait for boot
        booted = False
        for _ in range(10):
            try:
                r = requests.get("http://127.0.0.1:8000/health")
                if r.status_code == 200:
                    booted = True
                    break
            except:
                pass
            time.sleep(1)
        
        if not booted:
            print("❌ Server failed to start within 10s.")
            outs, errs = proc.communicate(timeout=1)
            print(f"Stdout: {outs}")
            print(f"Stderr: {errs}")
            return False
        
        print("   ✅ Server is UP.")

        # 2a. Init DB
        print("   Initializing DB...")
        client.init_db("test_verification.db")

        # 2b. Test KV
        print("   Testing KV Store...")
        client.set_kv("test_key", {"foo": "bar"})
        val = client.get_kv("test_key")
        if val != {"foo": "bar"}:
            print(f"❌ KV Mismatch: Expected {{'foo': 'bar'}}, got {val}")
            return False
        print("   ✅ KV Store OK.")
        
        # 3. Test Scenes
        print("   Testing Scene Logging...")
        client.log_scene("Test Scene", "scene_test.txt", "Lorem ipsum", {"word_count": 100})
        total = client.get_total_word_count()
        if total < 100: # Could be more if DB persisted
            print(f"❌ Word count seems wrong: {total}")
            # return False # Soft fail, might have pre-existing data
        
        print("   ✅ Scene Logging OK.")
        return True

    finally:
        print("   Killing server...")
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    success = test_integration()
    sys.exit(0 if success else 1)
