import ipaddress
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

SUFFIXES = (".myqcloud.com", ".tencentcos.cn", ".aliyuncs.com")


def validate_download_url(url: str):
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not host.endswith(SUFFIXES)
    ):
        raise ValueError("供应商下载地址不在允许的 HTTPS 域名范围内")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("禁止从私有网络地址下载资产")


def download(url: str, destination: Path, limit: int = 150 * 1024 * 1024):
    part = destination.with_suffix(destination.suffix + ".part")
    try:
        with httpx.Client(timeout=60, trust_env=False) as client:
            for _ in range(4):
                validate_download_url(url)
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers["location"])
                        continue
                    response.raise_for_status()
                    total = 0
                    with part.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > limit:
                                raise ValueError("供应商产物超过本地下载大小限制")
                            handle.write(chunk)
                    if total == 0:
                        raise ValueError("供应商返回了空产物")
                    part.replace(destination)
                    return
        raise ValueError("供应商下载重定向次数过多")
    finally:
        part.unlink(missing_ok=True)
