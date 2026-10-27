"""Use the actual framework with an isolated data directory."""

import os
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = PLUGIN_ROOT.parent
FRAMEWORK = Path(os.environ.get("KIRAAI_ROOT", WORKSPACE / "KiraAI"))
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, str(FRAMEWORK))

from core.utils.path_utils import init_paths

TEST_DATA = Path(tempfile.mkdtemp(prefix="kira-phone-tests-"))
init_paths(data_dir=str(TEST_DATA))

# Framework package initialization must precede its internal leaf imports.
import core.plugin  # noqa: E402,F401
