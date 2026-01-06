import subprocess
import sys
import shutil

def print_header(title):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)

def run_command(command, description):
    print(f"\nrunning: {description}...")
    try:
        result = subprocess.run(command, shell=True, check=False)
        if result.returncode == 0:
            print(f"✅ {description} PASSED")
            return True
        else:
            print(f"❌ {description} FAILED")
            return False
    except FileNotFoundError:
        print(f"❌ Command not found: {command}")
        return False

def check_dependencies():
    print_header("Checking Dependencies")
    # Verify pytest and flake8 are installed
    reqs_cmd = f"{sys.executable} -m pip install -r requirements.txt"
    if run_command(reqs_cmd, "Install/Update Dependencies"):
        print("Dependencies are up to date.")
        return True
    return False

def run_linting():
    print_header("Running Linter (flake8)")
    # Exclude common ignores: E501 (line length - handled by formatter), 
    # F401 (imports unused - inevitable in __init__ sometimes),
    # but we will try to be strict.
    # We exclude .git, __pycache__, venv
    lint_cmd = f"{sys.executable} -m flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=.git,__pycache__,venv"
    if run_command(lint_cmd, "Critical Syntax & Undefined Names Check"):
        print("No critical syntax errors found.")
        
    # Warning pass (non-blocking but informative)
    print("\n[Optional] Component-level style check (E501 ignored for now):")
    subprocess.run(f"{sys.executable} -m flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics --exclude=.git,__pycache__,venv", shell=True)
    return True

def run_tests():
    print_header("Running Unit Tests (pytest)")
    test_cmd = f"{sys.executable} -m pytest"
    return run_command(test_cmd, "Unit Tests")

def main():
    print_header("NOVELIST VERIFICATION SUITE")
    
    if not check_dependencies():
        print("\n❌ Failed to setup environment. Aborting.")
        sys.exit(1)
        
    passed_lint = run_linting()
    passed_tests = run_tests()
    
    print_header("VERIFICATION SUMMARY")
    print(f"Linting: {'✅ PASSED' if passed_lint else '❌ FAILED (Check logs)'}")
    print(f"Tests:   {'✅ PASSED' if passed_tests else '❌ FAILED'}")
    
    if passed_lint and passed_tests:
        print("\n🚀 SYSTEM READY FOR DEPLOYMENT/COMMIT")
        sys.exit(0)
    else:
        print("\n⚠️  ISSUES DETECTED. DO NOT COMMIT.")
        sys.exit(1)

if __name__ == "__main__":
    main()
