import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from itp.api import create_app
from itp.config import Settings
from itp.schemas import JobRequest


def client_for(settings):
    return TestClient(create_app(settings, start_worker=False), base_url="http://localhost:8000")


def test_empty_configuration_allows_upload_but_never_submits(tmp_path, image_bytes):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    with client_for(settings) as client:
        caps = client.get("/api/capabilities").json()
        assert not caps["geometry"] and not caps["pose"]
        upload = client.post("/api/assets", files={"file": ("character.png", image_bytes)})
        assert upload.status_code == 201
        asset = upload.json()
        assert "filename" not in asset
        assert client.get(asset["url"]).status_code == 200
        result = client.post("/api/jobs", json={"front": asset["id"]})
        assert result.status_code == 503
        assert client.get("/api/jobs").json() == []


def test_upload_validation_and_no_exif(settings, image_bytes):
    with client_for(settings) as client:
        assert (
            client.post("/api/assets", files={"file": ("fake.png", b"not an image")}).status_code
            == 422
        )
        out = io.BytesIO()
        Image.new("RGB", (10, 10)).save(out, format="PNG")
        assert (
            client.post("/api/assets", files={"file": ("small.png", out.getvalue())}).status_code
            == 422
        )
        assert (
            client.post(
                "/api/assets?remove_background=true", files={"file": ("a.png", image_bytes)}
            ).status_code
            == 503
        )
        upload = client.post("/api/assets", files={"file": ("../../evil.png", image_bytes)}).json()
        file = client.get(upload["url"])
        assert Image.open(io.BytesIO(file.content)).size == (256, 256)
        assert not (settings.data_dir / "evil.png").exists()


def test_local_origin_and_secret_redaction(settings, image_bytes):
    with client_for(settings) as client:
        assert (
            client.post(
                "/api/assets",
                headers={"Origin": "https://evil.example"},
                files={"file": ("a.png", image_bytes)},
            ).status_code
            == 403
        )
        assert "test-only" not in client.get("/api/capabilities").text
        assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_job_create_and_missing_asset(settings, image_bytes):
    with client_for(settings) as client:
        assert client.post("/api/jobs", json={"front": "0" * 32}).status_code == 422
        asset = client.post("/api/assets", files={"file": ("a.png", image_bytes)}).json()
        created = client.post("/api/jobs", json={"front": asset["id"]})
        assert created.status_code == 201
        job_id = created.json()["id"]
        assert client.get(f"/api/jobs/{job_id}").json()["state"] == "queued"
        assert client.post(f"/api/jobs/{job_id}/review", json={"approve": True}).status_code == 409
        assert client.get("/api/assets/not-found/file").status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"pose_mode": "custom"},
        {"pose_mode": "a-pose", "views": {"left": "a" * 32}},
        {
            "pose_mode": "custom",
            "pose_reference": "a" * 32,
            "rig": True,
            "neutral_pose_confirmed": True,
        },
        {"rig": True},
        {"face_count": 1},
    ],
)
def test_invalid_workflows(overrides):
    with pytest.raises(ValueError):
        JobRequest(front="f" * 32, **overrides)


def test_foreign_endpoints_rejected():
    with pytest.raises(ValueError):
        Settings(_env_file=None, pose_endpoint="https://dashscope-intl.aliyuncs.com/anything")
    with pytest.raises(ValueError):
        Settings(_env_file=None, tencent_endpoint="hunyuan.intl.tencentcloudapi.com")
