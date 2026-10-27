"""Run real JVM TLS/close tests with throwaway certificates and resolved Gradle jars."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java-home', default=os.environ.get('JAVA_HOME'))
    parser.add_argument('--gradle-home', type=Path, default=Path(os.environ.get('GRADLE_USER_HOME', Path.home() / '.gradle')))
    args = parser.parse_args()
    suffix = '.exe' if os.name == 'nt' else ''
    def tool(name):
        value = str(Path(args.java_home) / 'bin' / (name + suffix)) if args.java_home else shutil.which(name)
        if not value or not Path(value).is_file():
            raise SystemExit('JDK required: pass --java-home')
        return value
    def jar(group, artifact, version):
        matches = list((args.gradle_home / 'caches/modules-2/files-2.1' / group / artifact / version).glob('*/' + artifact + '-' + version + '.jar'))
        if len(matches) != 1:
            raise SystemExit(f'Build Android first to resolve {artifact}:{version}; check --gradle-home')
        return str(matches[0].resolve())
    jars = [jar('org.java-websocket', 'Java-WebSocket', '1.5.7'), jar('org.slf4j', 'slf4j-api', '2.0.16')]
    def run(command):
        result = subprocess.run(command, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))
        return result.stdout
    with tempfile.TemporaryDirectory(prefix='kira-tls-') as directory:
        directory = Path(directory)
        for name, start, validity in [('valid', '-1d', '30'), ('expired', '-3d', '1')]:
            keys = directory / (name + '.p12')
            run([tool('keytool'), '-genkeypair', '-alias', 'test', '-keyalg', 'RSA', '-keysize', '2048',
                 '-dname', 'CN=127.0.0.1', '-ext', 'SAN=IP:127.0.0.1', '-startdate', start, '-validity', validity,
                 '-keystore', str(keys), '-storetype', 'PKCS12', '-storepass', 'test-only', '-keypass', 'test-only', '-noprompt'])
            der = run([tool('keytool'), '-exportcert', '-alias', 'test', '-keystore', str(keys), '-storepass', 'test-only'])
            (directory / (name + '.sha256')).write_text(hashlib.sha256(der).hexdigest(), encoding='ascii')
        source = ROOT / 'android-app/app/src/main/java/top/kira/phone'
        tests = ROOT / 'android-app/tests'
        run([tool('javac'), '-encoding', 'UTF-8', '-cp', os.pathsep.join(jars), '-d', str(directory),
             str(source / 'SocketSecurity.java'), str(source / 'ServerAddress.java'),
             str(tests / 'SocketSecurityTest.java'), str(tests / 'SocketStopTest.java')])
        for test in ['top.kira.phone.SocketSecurityTest', 'SocketStopTest']:
            print(run([tool('java'), '-cp', os.pathsep.join(jars + [str(directory)]), test, str(directory)]).decode().strip())


if __name__ == '__main__':
    main()
