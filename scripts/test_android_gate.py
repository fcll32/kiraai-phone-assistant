"""Run command and server-address checks on the JVM without a phone or emulator."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--java-home", default=os.environ.get("JAVA_HOME"))
args = parser.parse_args()
suffix = ".exe" if os.name == "nt" else ""
java = str(Path(args.java_home) / "bin" / ("java" + suffix)) if args.java_home else shutil.which("java")
javac = str(Path(args.java_home) / "bin" / ("javac" + suffix)) if args.java_home else shutil.which("javac")
if not java or not javac:
    raise SystemExit("JDK is required; pass --java-home")
with tempfile.TemporaryDirectory(prefix="phone-gate-") as directory:
    subprocess.run([javac, "-encoding", "UTF-8", "-d", directory,
                    str(ROOT / "android-app/app/src/main/java/top/kira/phone/AppCatalog.java"),
                    str(ROOT / "android-app/tests/AppCatalogTest.java"),
                    str(ROOT / "android-app/app/src/main/java/top/kira/phone/CommandGate.java"),
                    str(ROOT / "android-app/tests/CommandGateTest.java"),
                    str(ROOT / "android-app/app/src/main/java/top/kira/phone/ConnectionPassword.java"),
                    str(ROOT / "android-app/tests/ConnectionPasswordTest.java"),
                    str(ROOT / "android-app/app/src/main/java/top/kira/phone/ServerAddress.java"),
                    str(ROOT / "android-app/tests/ServerAddressTest.java"),
                    str(ROOT / "android-app/app/src/main/java/top/kira/phone/ConnectionFailure.java"),
                    str(ROOT / "android-app/tests/ConnectionFailureTest.java"),
                    str(ROOT / "android-app/app/src/main/java/top/kira/phone/VoiceVad.java"),
                    str(ROOT / "android-app/tests/VoiceVadTest.java"),
                    str(ROOT / "android-app/app/src/main/java/top/kira/phone/VirtualMicSignal.java"),
                    str(ROOT / "android-app/tests/VirtualMicSignalTest.java")], check=True)
    subprocess.run([java, "-cp", directory, "top.kira.phone.ConnectionPasswordTest"], check=True)
    subprocess.run([java, "-cp", directory, "top.kira.phone.CommandGateTest"], check=True)
    subprocess.run([java, "-cp", directory, "top.kira.phone.ServerAddressTest"], check=True)
    subprocess.run([java, "-cp", directory, "top.kira.phone.ConnectionFailureTest"], check=True)
    subprocess.run([java, "-cp", directory, "top.kira.phone.VoiceVadTest"], check=True)
    subprocess.run([java, "-cp", directory, "top.kira.phone.VirtualMicSignalTest"], check=True)
    subprocess.run([java, "-cp", directory, "top.kira.phone.AppCatalogTest"], check=True)
