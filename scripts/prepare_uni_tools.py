"""Download the pinned official Windows uni-app build tools into .runtime/uni-tools."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent / ".runtime/uni-tools"
BASE = "https://update.liuyingyong.cn/hbuilderx/upgrade_repositories/5.26.2026091802/win32/plugins/contents/"
FILES = [
    ("hx", "https://download1.dcloud.net.cn/download/HBuilderX.5.26.2026091802.zip", "29afe8e7a432b94059bf7e01b1a596c9315ca0d4c6402a27a248547ea641577a", "."),
    ("sdk", "https://web-ext-storage.dcloud.net.cn/uni-app-x/sdk/Android-Vapor/Android-uni-app-x-vapor-SDK@101163-5.26.zip", "8613962af9b03789a4db29e42100887e83a996b69193407575d3c8143025727e", "sdk"),
]
PLUGINS = [
    ("uniapp-cli-vite", "5.26.2026091411.1611", "d92ae2f9998b05b8751fb0244a13534df951fffaee21e31fda0ce8743b3ee0be"),
    ("uniapp-uts-v1", "5.26.2026091619.3958", "b560d445cf179f950190a0592cf73774bc1ca7190d6fa4c03186dac02beb5f68"),
    ("unicloud", "2.0.70-2026091812", "33d13812717e75f82de56a4441d9d102c9bc615032748775ba2c43d4ef4b620f"),
    ("uni_modules", "1.0.7-2026063000", "c77d219f3db1e280b271a15a9de1834bc56da02ec46c60de4a29ecb724143f02"),
    ("uni_helpers", "3.0.1-2026081817", "6553663ef2bb4e6970c30ba7ce0c04eb6ce0342c4075ca2d353a2006bb66a924"),
    ("node18", "1.0.0.2026070820", "3cf1371bfcf4a6f664c5ee3bdc7d7577f66e5f9f22e6d7de3e7a8d5694d98dc0"),
]


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download_archive(name, url, digest):
    """Download with bounded retries; never accept a truncated or stale archive."""
    archive = ROOT / (name + ".zip")
    if archive.exists() and sha256_file(archive) == digest:
        return archive
    archive.unlink(missing_ok=True)
    partial = archive.with_name(archive.name + ".part")
    last_error = None
    for attempt in range(3):
        partial.unlink(missing_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=180) as response:
                expected = response.headers.get("Content-Length")
                received = 0
                with partial.open("wb") as target:
                    while chunk := response.read(1024 * 1024):
                        target.write(chunk)
                        received += len(chunk)
                    target.flush()
                    os.fsync(target.fileno())
            if expected is not None and received != int(expected):
                raise ValueError(f"Truncated download: received {received} of {expected} bytes")
            actual = sha256_file(partial)
            if actual != digest:
                raise ValueError(f"Checksum mismatch: expected {digest}, received {actual}")
            partial.replace(archive)
            return archive
        except Exception as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Failed to download {url} after 3 attempts: {last_error}") from last_error


def install(item):
    name, url, digest, directory = item
    archive = download_archive(name, url, digest)
    marker = ROOT / (name + ".verified")
    if marker.exists() and marker.read_text() == digest:
        return
    destination = (ROOT / directory).resolve()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            path = (destination / info.filename).resolve()
            if not path.is_relative_to(destination):
                raise ValueError("Archive path escapes destination")
        bundle.extractall("\\\\?\\" + str(destination) if os.name == "nt" else destination)
    marker.write_text(digest)
    print(f"Verified and extracted {name}", flush=True)


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("The pinned HBuilderX compiler distribution is for Windows.")
    ROOT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(install, FILES))
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(install, [(name, BASE + name + "." + version + ".zip", digest,
                                "HBuilderX/plugins/" + name) for name, version, digest in PLUGINS]))
