import hashlib
import importlib.util
from pathlib import Path
import shutil
import ssl
import subprocess

import pytest

spec = importlib.util.spec_from_file_location("public_ip", Path(__file__).with_name("setup_public_ip.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("address", ["203.0.113.10", "2001:db8::10"])
def test_ip_certificate_fingerprint_and_no_overwrite(tmp_path, address):
    if not shutil.which("openssl"):
        pytest.skip("OpenSSL is required")
    directory, url, fingerprint = module.generate(address, 8443, "http://127.0.0.1:5267", tmp_path)
    cert = directory / "cert.pem"
    subprocess.run(["openssl", "x509", "-in", str(cert), "-noout", "-checkip", address], check=True, capture_output=True)
    der = ssl.PEM_cert_to_DER_cert(cert.read_text())
    assert fingerprint == hashlib.sha256(der).hexdigest()
    host = f"[{address}]" if ":" in address else address
    assert url == f"wss://{host}:8443/ws/plugin/phone_control/device"
    token = (directory / "device-secret.txt").read_text().strip()
    assert len(token) >= 32
    phone_config = (directory / "app-config.txt").read_text(encoding="utf-8")
    assert f"服务器地址：{host}:8443" in phone_config
    assert f"连接密码：{token}" in phone_config
    assert f"服务器校验码：{fingerprint}" in phone_config
    assert "/ws/plugin/" not in phone_config
    config = (directory / "nginx-phone.conf").read_text()
    assert "location = /ws/plugin/phone_control/device" in config
    assert 'location / { return 404; }' in config
    with pytest.raises(ValueError, match="already contains"):
        module.generate(address, 8443, "http://127.0.0.1:5267", tmp_path)
    assert (directory / "device-secret.txt").read_text().strip() == token


@pytest.mark.parametrize("ip,port,upstream", [
    ("bad IP", 8443, "http://127.0.0.1:5267"),
    ("203.0.113.10", 65536, "http://127.0.0.1:5267"),
    ("203.0.113.10", 8443, "http://127.0.0.1;injected"),
    ("203.0.113.10", 8443, "http://user:pass@localhost"),
    ("203.0.113.10", 8443, "http://127.0.0.1:bad"),
    ("203.0.113.10", 8443, "http://127.0.0.1:0"),
])
def test_invalid_config_rejected_before_generating_credentials(tmp_path, ip, port, upstream):
    with pytest.raises(ValueError):
        module.generate(ip, port, upstream, tmp_path / "output")
    assert not (tmp_path / "output").exists()
