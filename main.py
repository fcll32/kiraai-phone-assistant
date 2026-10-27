"""GitHub-installable entry point for the KiraAI Phone Assistant plugin.

The repository keeps the application, Android client and plugin together. KiraAI
installs a plugin from the repository root, so this shim exposes the plugin class
from the ``phone_control`` package while leaving the project layout intact.
"""
from pathlib import Path
import sys

PLUGIN_ROOT = Path(__file__).resolve().parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from phone_control.main import PhoneControlPlugin  # noqa: E402,F401
