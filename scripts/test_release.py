import hashlib
import json
from pathlib import Path
import struct
import zipfile

import package_release
from package_plugin import build_plugin, FILES, PLUGIN
from package_release import source_files
from sync_release import synchronize


def test_offline_apk_includes_official_modal_module():
    # uni.showModal is implemented by _uni-modal, not by uni-prompt.
    # Checking only the page resources lets the APK build without its runtime provider.
    gradle = (Path(__file__).parent.parent / "uni-app/native-android/app/build.gradle").read_text(encoding="utf-8")
    assert "'uni-modal-release.aar'" in gradle
    sdk = next((Path(__file__).parent.parent / ".runtime/uni-sdk").glob("*/SDK/libs/uni-modal-release.aar"), None)
    if sdk is None:
        return  # The source-only CI still checks the dependency declaration.
    with zipfile.ZipFile(sdk) as aar, zipfile.ZipFile(aar.open("classes.jar")) as jar:
        expected = jar.read("uts/sdk/modules/DCloudUniModal/UniUTSMethodRegister.class")
    assert struct.pack(">I", 0xCAFEBABE) == expected[:4]


def test_metadata_and_installation_identifiers_are_consistent():
    release = synchronize()
    assert release["plugin_id"] == "phone_control"
    assert release["application_id"] == "top.kira.phone"


def test_plugin_archive_has_required_modules_and_no_runtime_config(tmp_path):
    target = build_plugin(tmp_path)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {"phone_control/" + name for name in FILES}
        assert "phone_control/protocol.py" in archive.namelist()
        assert "phone_control/新手使用说明.md" in archive.namelist()
        assert "phone_control/server.py" in archive.namelist()
        assert "phone_control/requirements.txt" in archive.namelist()
        assert "phone_control/web/index.html" in archive.namelist()
        assert "phone_control/config.json" not in archive.namelist()
        assert json.loads(archive.read("phone_control/manifest.json")) == json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))


def test_repository_root_is_installable_plugin():
    root = Path(__file__).parent.parent
    plugin = root / "phone_control"
    for name in ("manifest.json", "schema.json"):
        assert json.loads((root / name).read_text(encoding="utf-8")) == json.loads(
            (plugin / name).read_text(encoding="utf-8")
        )
    assert (root / "main.py").is_file()
    assert (root / "requirements.txt").read_text(encoding="utf-8") == (
        plugin / "requirements.txt"
    ).read_text(encoding="utf-8")


def test_source_distribution_excludes_builds_and_secrets():
    files = source_files()
    assert ".github/workflows/build.yml" in files
    assert "release.json" in files
    assert "manifest.json" in files
    assert "schema.json" in files
    assert "main.py" in files
    assert "新手使用说明.md" in files
    assert "phone_control/protocol.py" in files
    assert "phone_control/web/index.html" in files
    assert "uni-app/pages/index/index.uvue" in files
    assert "uni-app/uni_modules/kira-phone/utssdk/app-android/config.json" in files
    assert "uni-app/native-android/app/build.gradle" in files
    assert "phone_control/config.json" not in files
    assert not any("/build/" in name or "/unpackage/" in name or "/node_modules/" in name
                   or name.endswith((".apk", ".pyc", ".pem", ".keystore")) for name in files)


def test_release_packages_standalone_chinese_guide_with_valid_checksums(tmp_path, monkeypatch):
    files = source_files()
    guide_name = "新手使用说明.md"
    guide_content = files[guide_name].read_bytes()
    (tmp_path / guide_name).write_bytes(guide_content)
    monkeypatch.setattr(package_release, "ROOT", tmp_path)
    monkeypatch.setattr(package_release, "source_files", lambda: files)
    output, _ = package_release.package()
    assert (output / guide_name).read_bytes() == guide_content
    entries = (output / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert {line.split("  ", 1)[1] for line in entries} == {
        path.name for path in output.iterdir() if path.name != "SHA256SUMS.txt"
    }
    assert any(line.endswith("  " + guide_name) for line in entries)
    for line in entries:
        expected, name = line.split("  ", 1)
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected


def test_release_keeps_apk_separate_from_installable_plugin(tmp_path, monkeypatch):
    apk = tmp_path / "fixture.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("classes.dex", b"packaging fixture, not an installable app")
        archive.writestr("assets/licenses/Java-WebSocket-LICENSE.txt", b"fixture")
    files = source_files()
    (tmp_path / "新手使用说明.md").write_bytes(files["新手使用说明.md"].read_bytes())
    monkeypatch.setattr(package_release, "ROOT", tmp_path)
    monkeypatch.setattr(package_release, "source_files", lambda: files)
    output, _ = package_release.package(apk=apk)
    version = synchronize()["version"]
    assert (output / f"KiraAI-Phone-Assistant-{version}.apk").read_bytes() == apk.read_bytes()
    target = output / f"phone_control-{version}.zip"
    with zipfile.ZipFile(target) as archive:
        assert not any(i.filename.endswith(".apk") for i in archive.infolist())
        assert sum(i.file_size for i in archive.infolist()) < 50 * 1024 * 1024
    assert target.stat().st_size < 50 * 1024 * 1024
