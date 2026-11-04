"""Step 0 of the skill, the same on Windows, macOS and Linux. Standard library only.

Usage: python3 setup.py <unity_project_root>        (Windows: py -3 setup.py <root>, or python setup.py <root>)
1. Python venv in ~/.cache/datdb-uienv (kept across sessions and projects) with psd-tools, numpy, pillow.
2. Copies unity/UIBuilder.cs into <root>/Assets/_Project/Editor/ when the installed copy differs in any way.
Prints JSON: {"python": venv interpreter (run every script with it), "skill": this skill's folder,
"uibuilder": "up-to-date" | "INSTALLED", "errors": [...]}.
"""
import filecmp
import json
import os
import shutil
import subprocess
import sys

PACKAGES = ["psd-tools>=1.9", "numpy", "pillow"]
SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = os.path.join(os.path.expanduser("~"), ".cache", "datdb-uienv")


def venv_python():
    if os.name == "nt":
        return os.path.join(VENV, "Scripts", "python.exe")
    return os.path.join(VENV, "bin", "python")


def ensure_venv(errors):
    py = venv_python()
    if not os.path.exists(py):
        subprocess.run([sys.executable, "-m", "venv", VENV], check=True)
    ok = subprocess.run([py, "-c", "import psd_tools, numpy, PIL"], capture_output=True).returncode == 0
    if not ok:
        r = subprocess.run([py, "-m", "pip", "install", "-q", *PACKAGES], capture_output=True, text=True)
        if r.returncode != 0:
            errors.append("pip install failed: " + (r.stderr or r.stdout)[-800:])
    return py.replace("\\", "/")   # Git Bash and C# strings take forward slashes on Windows too


def ensure_uibuilder(root, errors):
    src = os.path.join(SKILL, "unity", "UIBuilder.cs")
    dst = os.path.join(root, "Assets", "_Project", "Editor", "UIBuilder.cs")
    if not os.path.isdir(os.path.join(root, "Assets")):
        errors.append(f"{root} is not a Unity project (no Assets folder)")
        return None
    if os.path.exists(dst) and filecmp.cmp(src, dst, shallow=False):
        return "up-to-date"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    return "INSTALLED"


def main():
    if sys.version_info < (3, 9):
        raise SystemExit(f"Python 3.9+ needed, this is {sys.version.split()[0]}")
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    errors = []
    py = ensure_venv(errors)
    status = ensure_uibuilder(root, errors)
    print(json.dumps({"python": py, "skill": SKILL.replace("\\", "/"), "uibuilder": status, "errors": errors}, indent=1))


if __name__ == "__main__":
    main()
