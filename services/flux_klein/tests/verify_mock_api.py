"""Offline mock verification of the FLUX.2 Klein HTTP contract.

Runs the real FastAPI application with a stub engine injected through
``create_app(engine=...)``. This exercises routing, bearer authentication,
body limits, request validation, image decoding and response serialization
without torch, model weights or a GPU. It does not prove inference quality.
"""

import base64
import io
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
from itp_flux_klein_service.api import MAX_BODY_BYTES, MODEL_NAME, create_app  # noqa: E402

TOKEN = "mock-token-for-offline-verification"


def png_bytes(size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def data_url(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


class StubEngine:
    """Records calls and returns a fixed PNG instead of running Diffusers."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str, list[tuple[int, int]]]] = []

    def edit(self, images: list[Image.Image], prompt: str) -> bytes:
        self.calls.append((len(images), prompt, [image.size for image in images]))
        return png_bytes((768, 1024), (200, 60, 60))


def main() -> None:
    os.environ["ITP_KLEIN_API_TOKEN"] = TOKEN
    reference = png_bytes((512, 512), (20, 120, 200))
    engine = StubEngine()
    # No ``with`` block: the lifespan never runs, so the stub stays installed.
    client = TestClient(create_app(engine=engine))
    passed: list[str] = []

    response = client.get("/health")
    assert response.status_code == 200, response.text
    assert response.json() == {"ready": True, "model": MODEL_NAME, "error": None}, response.text
    passed.append("GET /health reports the injected engine as ready")

    body = {"model": MODEL_NAME, "prompt": "换一件红色上衣", "images": [data_url(reference)]}
    response = client.post("/v1/flux-klein/edit", json=body)
    assert response.status_code == 401, response.text
    response = client.post(
        "/v1/flux-klein/edit", json=body, headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401, response.text
    passed.append("POST rejects a missing and a wrong bearer token with 401")

    response = client.post(
        "/v1/flux-klein/edit", json=body, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["model"] == MODEL_NAME and len(result["data"]) == 1, result
    generated = base64.b64decode(result["data"][0]["b64_json"], validate=True)
    with Image.open(io.BytesIO(generated)) as image:
        assert image.size == (768, 1024) and image.format == "PNG", image.size
    assert engine.calls == [(1, "换一件红色上衣", [(512, 512)])], engine.calls
    passed.append("POST with one reference returns the stub PNG and reaches the engine once")

    four = {"model": MODEL_NAME, "prompt": "保留身份换装", "images": [data_url(reference)] * 4}
    response = client.post(
        "/v1/flux-klein/edit", json=four, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 200, response.text
    assert engine.calls[-1][0] == 4, engine.calls[-1]
    passed.append("POST accepts the four-reference maximum")

    five = {"model": MODEL_NAME, "prompt": "too many", "images": [data_url(reference)] * 5}
    response = client.post(
        "/v1/flux-klein/edit", json=five, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 422, response.text
    passed.append("POST rejects five references with 422")

    wrong_model = {"model": "flux-2-pro", "prompt": "x", "images": [data_url(reference)]}
    response = client.post(
        "/v1/flux-klein/edit", json=wrong_model, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 422, response.text
    passed.append("POST rejects an unsupported model with 422")

    invalid = {"model": MODEL_NAME, "prompt": "x", "images": ["not-a-data-url"]}
    response = client.post(
        "/v1/flux-klein/edit", json=invalid, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 422, response.text
    passed.append("POST rejects a non-data-URL reference with 422")

    reference_64 = data_url(png_bytes((64, 64), (0, 0, 0)))
    tiny = {"model": MODEL_NAME, "prompt": "x", "images": [reference_64]}
    response = client.post(
        "/v1/flux-klein/edit", json=tiny, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 422, response.text
    passed.append("POST rejects a reference below the 128 px minimum with 422")

    unloaded = TestClient(create_app(engine=None))
    response = unloaded.post(
        "/v1/flux-klein/edit", json=body, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 503, response.text
    assert unloaded.get("/health").json()["ready"] is False, "expected ready=false without weights"
    passed.append("POST reports 503 and /health ready=false when no weights are loaded")

    assert MAX_BODY_BYTES == 56 * 1024 * 1024, MAX_BODY_BYTES

    for index, item in enumerate(passed, 1):
        print(f"PASS {index}: {item}")
    print(f"mock API verification: {len(passed)}/{len(passed)} checks passed")
    print("scope: HTTP contract only; no weights, no torch, no GPU, no real inference")


if __name__ == "__main__":
    main()
