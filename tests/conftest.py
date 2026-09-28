import io

import pytest
from PIL import Image

from itp.config import Settings
from itp.storage import Store


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        segmentation_model=tmp_path / "missing.onnx",
        tencent_endpoint="ai3d.tencentcloudapi.com",
        tencent_region="ap-guangzhou",
        tencent_secret_id="test-only",
        tencent_secret_key="test-only",
        pose_endpoint="https://dashscope.aliyuncs.com/api/v1/services/aigc/"
        "multimodal-generation/generation",
        pose_api_key="test-only",
        poll_seconds=0.05,
    )


@pytest.fixture
def image_bytes():
    out = io.BytesIO()
    Image.new("RGB", (256, 256), "orange").save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def store(settings, image_bytes):
    storage = Store(settings.data_dir)
    asset_id, path = storage.new_asset_path("png")
    path.write_bytes(image_bytes)
    storage.add_asset(asset_id, path, "image", width=256, height=256)
    storage.test_image = asset_id
    return storage
