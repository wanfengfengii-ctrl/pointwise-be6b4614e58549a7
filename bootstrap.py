"""Run a workspace script with the pinned public pandas distribution."""
import importlib.metadata
import os
from pathlib import Path
import runpy
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
PINNED = {"numpy": "1.26.4", "pandas": "2.2.2"}

def ready():
    try:
        return all(importlib.metadata.version(k) == v for k, v in PINNED.items())
    except importlib.metadata.PackageNotFoundError:
        return False

def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit("usage: bootstrap.py --prepare | SCRIPT [ARGS...]")
    if not ready():
        if os.environ.get("INTEGER_MERGE_REVIEW_CHILD") == "1":
            raise SystemExit("pinned runtime is incomplete")
        env_root = ROOT / ".review-venv"
        executable = env_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not executable.exists():
            venv.EnvBuilder(with_pip=True, symlinks=(os.name != "nt")).create(env_root)
        subprocess.run([str(executable), "-m", "pip", "install",
                        "--disable-pip-version-check", "--only-binary=:all:",
                        "-r", str(ROOT / "requirements.txt")], check=True)
        child_env = dict(os.environ, INTEGER_MERGE_REVIEW_CHILD="1",
                         PYTHONNOUSERSITE="1")
        result = subprocess.run([str(executable), str(Path(__file__).resolve()), *args],
                                env=child_env, cwd=ROOT)
        raise SystemExit(result.returncode)
    if args == ["--prepare"]:
        print("pinned pandas merge runtime ready")
        return
    script = (ROOT / args[0]).resolve()
    if script.parent != ROOT or not script.is_file():
        raise SystemExit("script must be an existing repository-root file")
    sys.argv = [str(script), *args[1:]]
    runpy.run_path(str(script), run_name="__main__")

if __name__ == "__main__":
    main()
