"""Haijing multi-reference trial protocol supplied by the project owner."""

import base64
import binascii
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

from itp.preprocessing import MAX_UPLOAD, image_base64


def _download_image(client: httpx.Client, url: str) -> bytes:
    parsed = urlparse(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password
            or parsed.fragment or host == "localhost" or host.endswith(".localhost")
            or host.endswith(".local")):
        raise ValueError("海鲸返回的图片地址不可信")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("海鲸返回的图片地址不可信")
    # Never forward the API key or follow redirects to a result-image host.
    with client.stream("GET", url, follow_redirects=False) as response:
        response.raise_for_status()
        length = response.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_UPLOAD:
            raise ValueError("海鲸返回图片超过 10 MiB")
        raw = bytearray()
        for chunk in response.iter_bytes():
            if len(raw) + len(chunk) > MAX_UPLOAD:
                raise ValueError("海鲸返回图片超过 10 MiB")
            raw.extend(chunk)
        return bytes(raw)


def generate_haijing(
    client: httpx.Client, endpoint: str, api_key: str,
    image_paths: list[Path], prompt: str, model: str,
) -> bytes:
    """Send numbered JPEG base64 references; real relay acceptance is unverified."""
    payload = {"model": model, "prompt": prompt, "aspect_ratio": "3:4"}
    for index, path in enumerate(image_paths):
        field = "input_image" if index == 0 else f"input_image_{index + 1}"
        payload[field] = image_base64(path)
    try:
        response = client.post(
            endpoint, json=payload, headers={"Authorization": f"Bearer {api_key}"},
            follow_redirects=False,
        )
        response.raise_for_status()
        result = response.json()["data"][0]
        if result.get("b64_json"):
            encoded = result["b64_json"]
            if len(encoded) > 4 * ((MAX_UPLOAD + 2) // 3):
                raise ValueError("海鲸返回图片超过 10 MiB")
            raw = base64.b64decode(encoded, validate=True)
        elif result.get("url"):
            raw = _download_image(client, result["url"])
        else:
            raise ValueError("海鲸未返回 data[0].url 或 b64_json 图片结果")
    except httpx.HTTPStatusError as exc:
        # Do not echo response bodies: they may contain credentials or reference images.
        raise RuntimeError(
            f"海鲸生图失败（HTTP {exc.response.status_code}）；"
            "请检查密钥、模型权限、余额及参考图格式"
        ) from None
    except httpx.HTTPError:
        raise RuntimeError("海鲸生图连接失败或超时；请检查服务连接") from None
    except (KeyError, IndexError, TypeError, AttributeError, binascii.Error, json.JSONDecodeError):
        raise RuntimeError("海鲸图片响应格式无效；应返回 data[0].url 或 b64_json") from None
    if not raw:
        raise ValueError("海鲸返回了空图片")
    if len(raw) > MAX_UPLOAD:
        raise ValueError("海鲸返回图片超过 10 MiB")
    return raw
