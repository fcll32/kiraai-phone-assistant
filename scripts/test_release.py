import hashlib
import json
from pathlib import Path
import shutil
import struct
import zipfile

import pytest

import package_release
import sync_release
import sync_uni_native
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


@pytest.fixture
def release_copy(tmp_path, monkeypatch):
    for name, source in source_files().items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    monkeypatch.setattr(sync_release, "ROOT", tmp_path)
    monkeypatch.setattr(sync_uni_native, "ROOT", tmp_path)
    monkeypatch.setattr(sync_uni_native, "JAVA", tmp_path / "android-app/app/src/main/java/top/kira/phone")
    monkeypatch.setattr(sync_uni_native, "MODULE", tmp_path / "uni-app/uni_modules/kira-phone/utssdk/app-android")
    return tmp_path


def test_release_sync_updates_both_installation_manifests(release_copy):
    path = release_copy / "release.json"
    release = json.loads(path.read_text(encoding="utf-8"))
    release.update(version="2.3.4", version_code=42, core_version=">=3.1.0",
                   name="新版手机助手", name_en="Updated Phone Assistant")
    path.write_text(json.dumps(release, ensure_ascii=False), encoding="utf-8")
    synchronize(write=True)
    manifests = [json.loads((release_copy / name).read_text(encoding="utf-8"))
                 for name in ("manifest.json", "phone_control/manifest.json")]
    assert manifests[0] == manifests[1]
    for manifest in manifests:
        assert manifest["version"] == release["version"]
        assert manifest["core_version"] == release["core_version"]
        assert manifest["display_name"] == release["name_en"]
        assert manifest["locales"]["zh"]["display_name"] == release["name"]
    resource = (release_copy / "android-app/app/src/main/res/values/release.xml").read_text(encoding="utf-8")
    assert f'<string name="update_repository" translatable="false">{release["repository"]}</string>' in resource
    preview = (release_copy / "uni-app/lib/phone.js").read_text(encoding="utf-8")
    assert f"version: '{release['version']}'" in preview
    synchronize()


@pytest.mark.parametrize("field,value", [("version_code", 0), ("version_code", True),
                                         ("repository", "https://evil.test/owner/repo")])
def test_update_metadata_rejects_invalid_install_version_and_repository(release_copy, field, value):
    path = release_copy / "release.json"
    release = json.loads(path.read_text(encoding="utf-8"))
    release[field] = value
    path.write_text(json.dumps(release), encoding="utf-8")
    with pytest.raises(ValueError):
        synchronize(write=True)


@pytest.mark.parametrize("field, value", [
    ("version", "0.0.0"), ("core_version", ">=999.0.0"), ("display_name", "Stale name"),
])
def test_release_check_rejects_stale_root_manifest(release_copy, field, value):
    path = release_copy / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest[field] = value
    stale = json.dumps(manifest, ensure_ascii=False)
    path.write_text(stale, encoding="utf-8")
    with pytest.raises(ValueError, match="manifest.json"):
        synchronize()
    assert path.read_text(encoding="utf-8") == stale
    synchronize(write=True)
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(
        (release_copy / "phone_control/manifest.json").read_text(encoding="utf-8"))
    synchronize()


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
        for name in ("panel.css", "panel.js", "assets/scene-settings.png", "assets/scene-pairing.png",
                     "assets/scene-guide.png", "assets/settings.png", "assets/link.png", "assets/guide.png",
                     "assets/call.png", "assets/shield.png", "assets/connected.png", "assets/rest.png", "assets/error.png", "assets/plugin-avatar.png"):
            key = "phone_control/web/" + name
            assert archive.read(key) == (Path(__file__).resolve().parents[1] / key).read_bytes()
        assert "phone_control/config.json" not in archive.namelist()
        assert json.loads(archive.read("phone_control/manifest.json")) == json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))
        icon = json.loads(archive.read("phone_control/manifest.json"))["icon"]
        assert archive.read("phone_control/" + icon) == (PLUGIN / "web/assets/plugin-avatar.png").read_bytes()


def test_repository_root_is_installable_plugin():
    root = Path(__file__).parent.parent
    plugin = root / "phone_control"
    for name in ("manifest.json", "schema.json"):
        assert json.loads((root / name).read_text(encoding="utf-8")) == json.loads(
            (plugin / name).read_text(encoding="utf-8")
        )
    assert (root / "main.py").is_file()
    icon = json.loads((root / "manifest.json").read_text(encoding="utf-8"))["icon"]
    assert (root / icon).read_bytes() == (plugin / icon).read_bytes()
    assert (root / "requirements.txt").read_text(encoding="utf-8") == (
        plugin / "requirements.txt"
    ).read_text(encoding="utf-8")


def test_source_distribution_excludes_builds_and_secrets():
    files = source_files()
    assert ".github/workflows/build.yml" in files
    assert "release.json" in files
    assert "manifest.json" in files
    assert "icon.png" in files
    assert "phone_control/icon.png" in files
    assert "android-app/app/src/main/res/drawable-nodpi/kira_launcher_art.png" in files
    assert "schema.json" in files
    assert "main.py" in files
    assert "新手使用说明.md" in files
    assert "phone_control/protocol.py" in files
    assert "phone_control/web/index.html" in files
    assert "phone_control/web/panel.css" in files
    assert "phone_control/web/panel.js" in files
    assert "phone_control/web/assets/scene-settings.png" in files
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
    notes = "# 发布说明\n测试版本的更新内容。\n".encode("utf-8")
    (tmp_path / "RELEASE_NOTES.md").write_bytes(notes)
    monkeypatch.setattr(package_release, "ROOT", tmp_path)
    monkeypatch.setattr(package_release, "source_files", lambda: files)
    output, _ = package_release.package()
    assert (output / guide_name).read_bytes() == guide_content
    assert (output / "RELEASE_NOTES.md").read_bytes() == notes
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


def test_source_archive_and_export_keep_local_artwork(tmp_path, monkeypatch):
    # A clean checkout must render the supplied backdrop without a remote URL.
    files = source_files()
    name = "uni-app/static/kira-wallpaper.jpg"
    image = files[name].read_bytes()
    assert image.startswith(b"\xff\xd8")
    (tmp_path / "新手使用说明.md").write_bytes(files["新手使用说明.md"].read_bytes())
    monkeypatch.setattr(package_release, "ROOT", tmp_path)
    monkeypatch.setattr(package_release, "source_files", lambda: files)
    export = tmp_path / "export"
    output, _ = package_release.package(export=export)
    with zipfile.ZipFile(next(output.glob("*-source.zip"))) as archive:
        assert archive.read("give-ai-a-phone/" + name) == image
        for sticker in ("hello", "connected", "call", "device", "link", "guide", "about", "rest", "shield"):
            key = f"uni-app/static/companions/{sticker}.png"
            data = files[key].read_bytes()
            assert data.startswith(b"\x89PNG\r\n\x1a\n")
            assert data[25] == 6  # RGBA keeps the generated transparent background.
            assert archive.read("give-ai-a-phone/" + key) == data
            assert (export / key).read_bytes() == data
        for scene in ("device", "connection", "voice", "guide", "about", "menu"):
            key = f"uni-app/static/scenes/{scene}.png"
            data = files[key].read_bytes()
            assert data.startswith(b"\x89PNG\r\n\x1a\n")
            assert archive.read("give-ai-a-phone/" + key) == data
            assert (export / key).read_bytes() == data
    assert (export / name).read_bytes() == image
