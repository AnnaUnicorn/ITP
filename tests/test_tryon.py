from fastapi.testclient import TestClient
from pydantic import SecretStr

from itp.api import create_app
from itp.tryon import VIEWS


def test_tryon_requires_configuration_without_affecting_3d(settings, image_bytes):
    settings = settings.model_copy(update={"seedream_endpoint": ""})
    app = create_app(settings, start_worker=False)
    with TestClient(app, base_url="http://localhost:8000") as client:
        asset = client.post("/api/assets", files={"file": ("front.png", image_bytes)}).json()
        assert client.get("/api/capabilities").json()["tryon"] is False
        assert client.post("/api/jobs", json={"front": asset["id"]}).status_code == 201
        result = client.post("/api/tryons", json={
            "person": {view: asset["id"] for view in VIEWS},
            "garment": {view: asset["id"] for view in VIEWS},
            "consistent_confirmed": True,
        })
        assert result.status_code == 503


def test_tryon_six_results_continue_without_upload(settings, image_bytes):
    settings = settings.model_copy(update={
        "seedream_endpoint": "https://ark.cn-beijing.volces.com/api/v3/images/generations",
        "seedream_api_key": SecretStr("test-only"),
    })
    app = create_app(settings, start_worker=False)
    calls = []

    def fake_generate(paths, prompt, model):
        calls.append((len(paths), prompt, model))
        return image_bytes

    app.state.tryon_worker.provider.generate = fake_generate
    with TestClient(app, base_url="http://localhost:8000") as client:
        asset = client.post("/api/assets", files={"file": ("source.png", image_bytes)}).json()
        payload = {"name": "测试试穿", "person": {view: asset["id"] for view in VIEWS},
                   "garment": {view: asset["id"] for view in VIEWS}}
        created = client.post("/api/tryons", json=payload)
        assert created.status_code == 201, created.text
        tryon = created.json()
        assert client.post(f"/api/tryons/{tryon['id']}/continue").status_code == 409
        app.state.tryon_worker.run_job(tryon)
        ready = client.get(f"/api/tryons/{tryon['id']}").json()
        assert ready["state"] == "ready"
        assert set(ready["results"]) == set(VIEWS)
        assert [call[0] for call in calls] == [2, 5, 5, 5, 5, 5]
        assert all(call[2] == settings.seedream_model for call in calls)
        for asset_id in ready["results"].values():
            assert client.get(f"/api/assets/{asset_id}/file").status_code == 200
        continued = client.post(f"/api/tryons/{tryon['id']}/continue")
        assert continued.status_code == 201, continued.text
        request = continued.json()["request"]
        assert request["front"] == ready["results"]["front"]
        assert set(request["views"]) == set(VIEWS) - {"front"}
        assert request["views_consistent_confirmed"] is True


def test_tryon_input_must_have_both_six_view_sets(settings, image_bytes):
    settings = settings.model_copy(update={
        "seedream_endpoint": "https://ark.cn-beijing.volces.com/api/v3/images/generations",
        "seedream_api_key": SecretStr("test-only"),
    })
    app = create_app(settings, start_worker=False)
    with TestClient(app, base_url="http://localhost:8000") as client:
        asset = client.post("/api/assets", files={"file": ("source.png", image_bytes)}).json()
        result = client.post("/api/tryons", json={"person": {"front": asset["id"]},
                                                   "garment": {"front": asset["id"]}})
        assert result.status_code == 422
