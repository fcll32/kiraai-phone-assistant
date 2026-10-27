"""Generate an IP certificate, device secret and an Nginx WebSocket-only proxy."""

import argparse
import ipaddress
import os
from pathlib import Path
import secrets
import ssl
import hashlib
import subprocess
from urllib.parse import urlparse


def generate(ip, port, upstream, output):
    address = ipaddress.ip_address(ip)
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    parsed = urlparse(upstream)
    if parsed.scheme != "http" or not parsed.hostname or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("Upstream must be an HTTP origin, such as http://127.0.0.1:5267")
    if any(c.isspace() or c in ';{}$' for c in upstream):
        raise ValueError("Invalid upstream")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid upstream port")
    output = Path(output).resolve()
    if any(c in str(output) for c in '\n\r"$'):
        raise ValueError("Output path contains characters unsupported by Nginx")
    output.mkdir(parents=True, exist_ok=True)
    cert, key = output / "cert.pem", output / "private-key.pem"
    if cert.exists() or key.exists() or (output / "device-secret.txt").exists():
        raise ValueError("Output already contains credentials; use a new directory to avoid replacing active keys")
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-days", "365",
        "-nodes", "-keyout", str(key), "-out", str(cert), "-subj", f"/CN={address}",
        "-addext", f"subjectAltName=IP:{address}", "-addext", "extendedKeyUsage=serverAuth",
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    token = secrets.token_urlsafe(32)
    (output / "device-secret.txt").write_text(token + "\n", encoding="utf-8")
    der = ssl.PEM_cert_to_DER_cert(cert.read_text(encoding="ascii"))
    fingerprint = hashlib.sha256(der).hexdigest()
    host = f"[{address}]" if address.version == 6 else str(address)
    url = f"wss://{host}:{port}/ws/plugin/phone_control/device"
    (output / "app-config.txt").write_text(
        f"服务器地址：{host}:{port}\n连接密码：{token}\n服务器校验码：{fingerprint}\n", encoding="utf-8")
    config = f'''limit_conn_zone $binary_remote_addr zone=kira_phone_conn:10m;
limit_req_zone $binary_remote_addr zone=kira_phone_rate:10m rate=10r/m;
server {{
    listen {port} ssl;
    listen [::]:{port} ssl;
    server_name {address};
    ssl_certificate "{cert.as_posix()}";
    ssl_certificate_key "{key.as_posix()}";
    ssl_protocols TLSv1.2 TLSv1.3;
    location = /ws/plugin/phone_control/device {{
        limit_conn kira_phone_conn 5;
        limit_req zone=kira_phone_rate burst=10 nodelay;
        proxy_pass {upstream.rstrip('/')};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 90s;
        proxy_send_timeout 60s;
        proxy_buffering off;
    }}
    location / {{ return 404; }}
}}
'''
    (output / "nginx-phone.conf").write_text(config, encoding="utf-8")
    if os.name != "nt":
        for secret in (key, output / "device-secret.txt", output / "app-config.txt"):
            secret.chmod(0o600)
    return output, url, fingerprint


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True)
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--upstream", default="http://127.0.0.1:5267")
    parser.add_argument("--output", default=str(Path(__file__).parent / "generated"))
    args = parser.parse_args()
    directory, url, fingerprint = generate(args.ip, args.port, args.upstream, args.output)
    phone_address = urlparse(url).netloc
    print(f"已生成连接信息，文件夹：{directory}\n手机里填写的服务器地址：{phone_address}")
    print("打开 app-config.txt，按对应名称填写手机 App；连接密码也要填到 KiraAI 插件中。")
    print("接着按新手说明启用服务器连接。现在只生成了文件，还没有自动启用服务。")
