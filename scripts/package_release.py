"""Build a clean release directory containing sources, plugin, optional APK and hashes."""
import argparse
import hashlib
from pathlib import Path
import shutil
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_plugin import build_plugin
from sync_release import synchronize

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ("phone_control", "android-app", "uni-app", "deploy", "scripts", "third-party", ".github")
ROOT_FILES = ("README.md", "新手使用说明.md", "RELEASE_NOTES.md", "release.json", "THIRD_PARTY_NOTICES.md", ".gitignore", ".gitattributes", "manifest.json", "icon.png", "schema.json", "main.py", "requirements.txt")


def source_files():
    files = {name: ROOT / name for name in ROOT_FILES}
    for folder in SOURCE_DIRS:
        for path in (ROOT / folder).rglob("*"):
            relative = path.relative_to(ROOT)
            if not path.is_file() or any(part in {"__pycache__", ".pytest_cache", "build", ".gradle", "unpackage", "node_modules", ".hbuilderx"} or part.startswith("generated") for part in relative.parts):
                continue
            if path.name in {"local.properties", "app-config.txt", "device-secret.txt"} or relative.as_posix() == "phone_control/config.json":
                continue
            if path.suffix not in {".py", ".java", ".json", ".md", ".html", ".css", ".xml", ".gradle", ".txt", ".yml", ".uvue", ".uts", ".js", ".mjs", ".properties", ".jpg", ".png"}:
                continue
            files[relative.as_posix()] = path
    return files


def package(apk=None, export=None):
    release = synchronize()
    version = release["version"]
    output = ROOT / "dist" / version
    output.mkdir(parents=True, exist_ok=True)
    plugin = build_plugin(output)
    files = source_files()
    source = output / f"kiraai-phone-assistant-{version}-source.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, "give-ai-a-phone/" + name)
            if export:
                destination = Path(export) / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
    # GitHub release uploads sanitize non-ASCII filenames (e.g. to default.md).
    guide = output / "QUICKSTART.zh-CN.md"
    shutil.copy2(ROOT / "新手使用说明.md", guide)
    artifacts = [plugin, source, guide]
    notes = ROOT / "RELEASE_NOTES.md"
    if notes.is_file():
        shutil.copy2(notes, output / notes.name)
        artifacts.append(output / notes.name)
    if apk:
        apk = Path(apk).resolve()
        with zipfile.ZipFile(apk) as archive:
            if "classes.dex" not in archive.namelist() or "assets/licenses/Java-WebSocket-LICENSE.txt" not in archive.namelist():
                raise ValueError("Incomplete APK")
        target = output / f"KiraAI-Phone-Assistant-{version}.apk"
        if apk != target.resolve():
            shutil.copy2(apk, target)
        artifacts.insert(0, target)
    for archive in (plugin, source):
        with zipfile.ZipFile(archive) as package_zip:
            if package_zip.testzip() is not None:
                raise ValueError("Archive verification failed")
    (output / "README.txt").write_text(
        f"{release['name']} {version}\n\n"
        f"手机：安装 KiraAI-Phone-Assistant-{version}.apk。\n"
        "如提示版本过低或签名不一致，请先保存连接信息，再卸载旧 App、安装并重新填写；卸载会清除手机设置。\n"
        f"KiraAI：上传 phone_control-{version}.zip，安装并启用。插件 ZIP 不含 APK，手机安装包单独提供。\n"
        "第一次使用：安装插件 ZIP 后，打开 KiraAI 左侧的“手机连接”页面，填公网 IP 和允许使用的聊天。\n"
        "点击“保存并启动”后开始监听，以后重启自动恢复；密码和校验码在管理页复制；手机单独安装同目录的 APK，无需下载源码或运行服务器脚本。\n"
        "手机地址只填 公网IP:端口，其他内容自动补上。原来的完整地址也能继续用。\n"
        f"源码：kiraai-phone-assistant-{version}-source.zip，仅用于开发和修改，普通使用不需要。\n"
        "共用入口放行 TCP 5267，Docker 映射 5267:8443；备用管理映射 127.0.0.1:15267:5267。浏览器使用 https://公网IP:5267。\n"
        "若上传提示插件已存在，先卸载旧插件，保留插件配置和插件数据，再安装新版 ZIP。\n"
        "Android 8–10 不支持真实截图，Android 11 及以上可按需截图。\n"
        "当前为测试版本，还需要在你的手机和服务器上实际连接验证。\n", encoding="utf-8")
    artifacts.append(output / "README.txt")
    (output / "SHA256SUMS.txt").write_text("".join(
        hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in artifacts), encoding="utf-8")
    return output, len(files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path)
    parser.add_argument("--export", type=Path, help="Also copy clean source files to this directory")
    args = parser.parse_args()
    output, count = package(args.apk, args.export)
    print(f"Packaged {count} source files. Release directory: {output}")
