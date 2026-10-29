"""Keep Android and plugin release metadata aligned with release.json."""
import argparse
import json
from pathlib import Path
import re
import sys
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))


def synchronize(write=False):
    release = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
    if not re.fullmatch(r"\d+\.\d+\.\d+", release["version"]):
        raise ValueError("Expected a numeric major.minor.patch version")
    if type(release["version_code"]) is not int or not 1 <= release["version_code"] <= 2100000000:
        raise ValueError("Expected a positive Android internal version code")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", release["repository"]):
        raise ValueError("Expected a GitHub owner/repository update source")
    manifest_path = ROOT / "phone_control/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(version=release["version"], display_name=release["name_en"], core_version=release["core_version"])
    manifest["locales"]["zh"]["display_name"] = release["name"]
    gradle_path = ROOT / "android-app/app/build.gradle"
    gradle = gradle_path.read_text(encoding="utf-8")
    gradle = re.sub(r"versionCode \d+", f'versionCode {release["version_code"]}', gradle)
    gradle = re.sub(r"versionName '[^']+'", f'versionName \'{release["version"]}\'', gradle)
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    targets = {
        manifest_path: manifest_text,
        ROOT / "manifest.json": manifest_text,
        gradle_path: gradle,
        ROOT / "android-app/app/src/main/res/values/release.xml":
            '<resources>\n    <string name="app_name">' + escape(release["name"]) + '</string>\n'
            '    <string name="update_repository" translatable="false">' + escape(release["repository"]) + '</string>\n'
            f'    <integer name="protocol_version">{release["protocol"]}</integer>\n</resources>\n',
    }
    uni_path = ROOT / "uni-app/manifest.json"
    uni = json.loads(uni_path.read_text(encoding="utf-8"))
    if uni["app"]["distribute"]["android"]["packagename"] != release["application_id"]:
        raise ValueError("uni-app application ID must preserve upgrade compatibility")
    uni.update(name=release["name"], versionName=release["version"], versionCode=str(release["version_code"]))
    targets[uni_path] = json.dumps(uni, ensure_ascii=False, indent=2) + "\n"
    preview_path = ROOT / "uni-app/lib/phone.js"
    preview = preview_path.read_text(encoding="utf-8")
    targets[preview_path] = re.sub(r"version: '\d+\.\d+\.\d+'", f"version: '{release['version']}'", preview)
    bridge_path = ROOT / "uni-app/uni_modules/kira-phone/package.json"
    bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
    bridge["version"] = release["version"]
    targets[bridge_path] = json.dumps(bridge, ensure_ascii=False, indent=2) + "\n"
    runtime_path = ROOT / "android-app/app/src/main/java/top/kira/phone/PhoneRuntime.java"
    runtime = runtime_path.read_text(encoding="utf-8")
    targets[runtime_path] = re.sub(r"PROTOCOL_VERSION = \d+;", f"PROTOCOL_VERSION = {release['protocol']};", runtime)
    mismatched = []
    for path, expected in targets.items():
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            if write:
                path.write_text(expected, encoding="utf-8")
            else:
                mismatched.append(str(path.relative_to(ROOT)))
    if manifest["plugin_id"] != release["plugin_id"] or f"applicationId '{release['application_id']}'" not in gradle:
        raise ValueError("Do not change existing installation identifiers during an upgrade")
    protocol = (ROOT / "phone_control/protocol.py").read_text(encoding="utf-8")
    if f"PROTOCOL_VERSION = {release['protocol']}\n" not in protocol:
        raise ValueError("Protocol version mismatch")
    if mismatched:
        raise ValueError("Run scripts/sync_release.py --write: " + ", ".join(mismatched))
    from sync_uni_native import synchronize as sync_native
    sync_native(write)
    return release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    release = synchronize(args.write)
    print(f"Release {release['version']}: metadata synchronized")
