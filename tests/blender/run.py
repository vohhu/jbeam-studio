"""Runs tests/blender inside Blender.

    blender -b --factory-startup --python tests/blender/run.py [-- pytest arguments]

pytest is imported from JBS_PYTEST_PATH, by default `.blender-pytest` in the repository, filled with
`python -m pip install --target .blender-pytest pytest`; Blender itself is not changed.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, os.environ.get("JBS_PYTEST_PATH", str(ROOT / ".blender-pytest")))

import pytest  # noqa: E402

arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
code = pytest.main([str(ROOT / "tests" / "blender"), "-p", "no:cacheprovider", "-p", "no:faulthandler", "-q",
                    *arguments])
sys.stdout.flush()
sys.stderr.flush()
os._exit(int(code))
