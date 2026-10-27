"""Copy the reviewed Android services into the uni-app UTS module; check by default."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
JAVA = ROOT / "android-app/app/src/main/java/top/kira/phone"
MODULE = ROOT / "uni-app/uni_modules/kira-phone/utssdk/app-android"
CLASSES = ("AppCatalog", "ConnectionPassword", "CommandGate", "ConnectionFailure", "ConnectionService", "PhoneAccessibility", "ServerAddress", "PhoneRuntime",
           "SocketSecurity", "VoiceRuntime", "VoiceCallService", "VoiceVad",
           "VirtualMicRuntime", "VirtualMicService", "VirtualMicSignal")


def synchronize(write=False):
    pairs = [(JAVA / (name + ".java"), MODULE / (name + ".java")) for name in CLASSES]
    pairs += [(path, MODULE / "assets/licenses" / path.name)
              for path in (ROOT / "third-party").glob("*-LICENSE.txt")]
    stale = []
    for source, target in pairs:
        if not target.exists() or source.read_bytes() != target.read_bytes():
            if write:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            else:
                stale.append(str(target.relative_to(ROOT)))
    if stale:
        raise ValueError("Run scripts/sync_uni_native.py --write: " + ", ".join(stale))
    return len(pairs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    print(f"Checked {synchronize(args.write)} native files")
