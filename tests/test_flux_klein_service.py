import base64

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.flux_klein.itp_flux_klein_service.api import EditRequest, create_app, decode_image
from services.flux_klein.itp_flux_klein_service.inference import (
    MODEL_ARCHITECTURES,
    validate_model_config,
)


def test_flux_klein_service_decodes_real_image(image_bytes):
    encoded = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    image = decode_image(encoded)
    assert image.mode == "RGB"
    assert image.size == (256, 256)
    request = EditRequest(prompt="Change clothing", images=[encoded])
    assert request.model == "flux.2-klein-4b"


def test_flux_klein_service_rejects_invalid_references(image_bytes):
    encoded = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    with pytest.raises(ValidationError):
        EditRequest(prompt="test", images=[encoded] * 5)
    with pytest.raises(ValueError):
        decode_image("data:image/png;base64,not-valid-base64")


def test_klein_9b_contract_and_model_isolation(monkeypatch, image_bytes):
    class RecordingEngine:
        model_name = "flux.2-klein-9b"

        def __init__(self):
            self.calls = []

        def edit(self, images, prompt):
            self.calls.append((images, prompt))
            return image_bytes

    monkeypatch.setenv("ITP_KLEIN_API_TOKEN", "test-private-token")
    engine = RecordingEngine()
    client = TestClient(create_app(engine, model_name=engine.model_name))
    assert client.get("/health").json() == {
        "ready": True, "model": "flux.2-klein-9b", "error": None,
    }
    encoded = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    body = {"model": engine.model_name, "prompt": "Change clothing", "images": [encoded] * 4}
    assert client.post("/v1/flux-klein/edit", json=body).status_code == 401
    headers = {"Authorization": "Bearer test-private-token"}
    wrong = dict(body, model="flux.2-klein-4b")
    assert client.post("/v1/flux-klein/edit", json=wrong, headers=headers).status_code == 422
    assert engine.calls == []
    response = client.post("/v1/flux-klein/edit", json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["model"] == engine.model_name
    assert base64.b64decode(response.json()["data"][0]["b64_json"]) == image_bytes
    assert len(engine.calls[0][0]) == 4


def test_klein_9b_not_loaded_is_not_ready(monkeypatch, image_bytes):
    monkeypatch.setenv("ITP_KLEIN_MODEL_ID", "flux.2-klein-9b")
    monkeypatch.setenv("ITP_KLEIN_API_TOKEN", "test-private-token")
    # No lifespan context: verifies the unloaded contract without Torch or CUDA.
    client = TestClient(create_app())
    assert client.get("/health").json()["ready"] is False
    assert client.get("/health").json()["model"] == "flux.2-klein-9b"
    response = client.post("/v1/flux-klein/edit", headers={
        "Authorization": "Bearer test-private-token",
    }, json={"model": "flux.2-klein-9b", "prompt": "Change clothing", "images": [
        "data:image/png;base64," + base64.b64encode(image_bytes).decode(),
    ]})
    assert response.status_code == 503


def test_klein_rejects_wrong_architecture_and_unknown_model():
    for model_name, config in MODEL_ARCHITECTURES.items():
        validate_model_config(model_name, config)
    with pytest.raises(ValueError, match="does not match"):
        validate_model_config("flux.2-klein-9b", MODEL_ARCHITECTURES["flux.2-klein-4b"])
    with pytest.raises(ValueError, match="ITP_KLEIN_MODEL_ID"):
        create_app(model_name="unknown")
