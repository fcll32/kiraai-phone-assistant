"""Compile uni-app x with the matching HBuilderX 5.26 compiler, locally."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_uni_native import synchronize

ROOT = Path(__file__).resolve().parent.parent


def compile_app(hbuilderx, platform="android"):
    synchronize()
    hx = Path(hbuilderx).resolve()
    compiler = hx / "plugins/uniapp-cli-vite"
    node = hx / "plugins/node/node.exe"
    if not node.exists():
        raise ValueError("This pinned build uses the Windows HBuilderX 5.26 distribution and its bundled Node.")
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("UNI_") or key in {"HX_APP_ROOT", "HX_Version", "RUN_BY_HBUILDERX"}:
            del env[key]
    env["UNI_INPUT_DIR"] = str(ROOT / "uni-app")
    env["UNI_OUTPUT_DIR"] = str(ROOT / "uni-app/unpackage" / (
        "resources/app-android" if platform == "android" else "dist/build/web"))
    if platform == "android":
        env.update(UNI_APP_X="true", UNI_APP_X_DOM2="true", UNI_APP_PLATFORM="android", UNI_PLATFORM="app")
    subprocess.run([str(node), str(compiler / "node_modules/@dcloudio/vite-plugin-uni/bin/uni.js"),
                    "build", "-p", "app" if platform == "android" else "h5"],
                   cwd=compiler, env=env, check=True)
    return Path(env["UNI_OUTPUT_DIR"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hbuilderx", required=True, type=Path)
    parser.add_argument("--platform", choices=("android", "web"), default="android")
    args = parser.parse_args()
    print(compile_app(args.hbuilderx, args.platform))
