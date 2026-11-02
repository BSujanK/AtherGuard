"""Build the React dashboard into dashboard/dist (the folder the API serves at /).

    python -m aetherguard.serve.dashboard_build [--skip-install]

Runs `npm ci` (a clean install from package-lock.json) and `npm run build` in dashboard/. `--skip-install` keeps the
existing node_modules, for machines without the network.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import PROJECT_ROOT

DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
INDEX = Path("dist") / "index.html"


class BuildError(RuntimeError):
    """The dashboard could not be built (npm missing, or an npm step failed)."""


def build_dashboard(folder: Path = DASHBOARD_DIR, *, skip_install: bool = False, run=subprocess.run,
                    which=shutil.which) -> Path:
    """Run the npm steps in `folder` and return the built index.html; raises BuildError naming the failed step."""
    npm = which("npm")
    if npm is None:
        raise BuildError("npm was not found on PATH; install Node.js to build the dashboard")
    if not (folder / "package.json").is_file():
        raise BuildError(f"{folder.name}/package.json not found")
    steps = [[npm, "run", "build"]] if skip_install else [[npm, "ci"], [npm, "run", "build"]]
    for command in steps:
        completed = run(command, cwd=folder)
        if completed.returncode != 0:
            raise BuildError(f"`npm {' '.join(command[1:])}` exited with code {completed.returncode}")
    built = folder / INDEX
    if not built.is_file():
        raise BuildError(f"the build finished without producing {INDEX.as_posix()}")
    return built


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-install", action="store_true", help="do not run `npm ci`; build with the installed node_modules")
    args = parser.parse_args(argv)
    try:
        built = build_dashboard(skip_install=args.skip_install)
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"built {built.relative_to(PROJECT_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
