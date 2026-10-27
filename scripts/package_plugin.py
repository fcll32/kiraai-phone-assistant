"""Package only the plugin's distributable files."""
from pathlib import Path
import json
import zipfile

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "phone_control"
FILES = ["__init__.py", "main.py", "adb.py", "remote.py", "media.py", "protocol.py", "server.py", "voice.py",
         "manifest.json", "schema.json", "requirements.txt", "web/index.html", "README.md", "ADB.md", "新手使用说明.md"]

def build_plugin(output_dir=None):
    version = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))["version"]
    target = (Path(output_dir) if output_dir else ROOT / "dist" / version) / f"phone_control-{version}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as output:
        for name in FILES:
            source = ROOT / name if name == "新手使用说明.md" else PLUGIN / name
            output.write(source, f"phone_control/{name}")
    # Kira limits both the uploaded ZIP and its total extracted size to 50 MiB.
    with zipfile.ZipFile(target) as archive:
        too_large = target.stat().st_size > 50 * 1024 * 1024 or sum(i.file_size for i in archive.infolist()) > 50 * 1024 * 1024
    if too_large:
        target.unlink()
        raise ValueError("Plugin ZIP exceeds Kira's 50 MiB size limit")
    return target


if __name__ == "__main__":
    print(build_plugin())
