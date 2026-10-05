"""Accept documented relay settings without pretending an unknown edit protocol works."""

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from itp.api import create_app
from itp.config import HAIJING_GENERATION_ENDPOINT, Settings
from itp.tryon import FluxProvider


@pytest.mark.parametrize("provider", ["flux", "flux_max"])
def test_haijing_settings_save_but_never_create_text_only_tryon(
    settings, tmp_path, image_bytes, provider,
):
    config = tmp_path / ".env"
    app = create_app(settings, start_worker=False, config_path=config)
    with TestClient(app, base_url="http://localhost:8000") as client:
        response = client.patch("/api/settings", json={
            f"{provider}_endpoint": HAIJING_GENERATION_ENDPOINT,
            f"{provider}_api_key": "test-relay-key",
        })
        assert response.status_code == 200
        assert "test-relay-key" not in response.text
        assert response.json()[f"{provider}_api_key_set"] is True
        restored = Settings(_env_file=config)
        assert getattr(restored, f"{provider}_endpoint") == HAIJING_GENERATION_ENDPOINT
        caps = client.get("/api/capabilities").json()
        assert caps["tryon_providers"][provider] is True
        assert "参考图片字段尚未确认" in caps["tryon_provider_issues"][provider]
        asset = client.post("/api/assets", files={"file": ("front.png", image_bytes)}).json()
        task = client.post("/api/tryons", json={
            "provider": provider, "person": {"front": asset["id"]},
            "garment": {"front": asset["id"]},
        })
        assert task.status_code == 503
        assert "参考图片字段尚未确认" in task.json()["detail"]
        assert client.get("/api/tryons").json() == []
        assert client.post("/api/jobs", json={"front": asset["id"]}).status_code == 201


def test_haijing_direct_adapter_cannot_accidentally_charge_for_text_generation(settings, store):
    settings = settings.model_copy(update={
        "flux_max_endpoint": HAIJING_GENERATION_ENDPOINT,
        "flux_max_api_key": SecretStr("unused-test-key"),
    })

    def unexpected_request(request):
        raise AssertionError("No HTTP request may be sent with unknown reference fields")

    with httpx.Client(transport=httpx.MockTransport(unexpected_request)) as client:
        with pytest.raises(RuntimeError, match="参考图片字段尚未确认"):
            FluxProvider(settings, client, provider="flux_max").generate(
                [store.path(store.test_image)], "Keep identity", "flux-2-max",
            )


@pytest.mark.parametrize("endpoint", [
    "http://api.haijingai.com/v2/images/generations",
    "https://api.haijingai.com/v2/images/generations?api_key=secret",
    "https://api.haijingai.com.evil.example/v2/images/generations",
])
def test_only_exact_documented_relay_address_is_accepted(endpoint):
    with pytest.raises(ValueError):
        Settings(_env_file=None, flux_max_endpoint=endpoint)
