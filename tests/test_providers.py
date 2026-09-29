import json
from unittest.mock import patch

import httpx
import pytest

from itp.downloads import validate_download_url
from itp.providers import PoseProvider, ProviderError, TencentProvider


def test_tencent_uses_official_request_schema_and_no_network(settings):
    captured = []

    def call(self, action, params, **kwargs):
        captured.append((action, params))
        return json.dumps({"Response": {"JobId": "123", "RequestId": "req"}})

    with patch("tencentcloud.ai3d.v20250513.ai3d_client.Ai3dClient.call", call):
        result = TencentProvider(settings).submit(
            "geometry",
            {
                "Model": "3.1",
                "ImageBase64": "test",
                "GenerateType": "Geometry",
                "MultiViewImages": [{"ViewType": "left", "ViewImageBase64": "test-left"}],
            },
        )
    assert result["JobId"] == "123"
    assert captured[0][0] == "SubmitHunyuanTo3DProJob"
    assert captured[0][1]["MultiViewImages"][0]["ViewType"] == "left"


def test_qwen_character_and_reference_order(settings, store):
    captured = []

    def post(self, url, **kwargs):
        captured.append(kwargs["json"])
        return httpx.Response(
            200,
            json={
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [{"image": "https://example.aliyuncs.com/result.png"}]
                            }
                        }
                    ]
                },
                "request_id": "123",
            },
        )

    with patch.object(httpx.Client, "post", post):
        result = PoseProvider(settings).edit(
            store.path(store.test_image), store.path(store.test_image), "custom", 42
        )
    content = captured[0]["input"]["messages"][0]["content"]
    assert content[0]["image"].startswith("data:image/jpeg;base64,")
    assert content[1]["image"].startswith("data:image/jpeg;base64,")
    assert "image 2" in content[2]["text"]
    assert result["request_id"] == "123"


def test_tencent_error_explains_service_state_without_raw_message(settings):
    from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
        TencentCloudSDKException,
    )

    def call(self, action, params, **kwargs):
        raise TencentCloudSDKException(
            "ResourceUnavailable.NotExist", "private vendor response", "request-123"
        )

    with patch("tencentcloud.ai3d.v20250513.ai3d_client.Ai3dClient.call", call):
        with pytest.raises(ProviderError) as error:
            TencentProvider(settings).submit("geometry", {"ImageBase64": "test"})
    assert "服务未开通或计费状态异常" in str(error.value)
    assert "ResourceUnavailable.NotExist" in str(error.value)
    assert "RequestId=request-123" in str(error.value)
    assert "private vendor response" not in str(error.value)


def test_pose_http_error_explains_key_without_raw_message(settings, store):
    def post(self, url, **kwargs):
        return httpx.Response(401, json={"code": "InvalidApiKey", "message": "private response"})

    with patch.object(httpx.Client, "post", post):
        with pytest.raises(ProviderError) as error:
            PoseProvider(settings).edit(store.path(store.test_image), None, "t-pose", 42)
    assert "API Key 无效" in str(error.value)
    assert "private response" not in str(error.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://test.myqcloud.com/file",
        "https://localhost/a",
        "https://127.0.0.1/a",
        "https://test.myqcloud.com.evil.com/a",
        "https://user:password@test.myqcloud.com/a",
    ],
)
def test_download_rejects_untrusted_urls(url):
    with pytest.raises(ValueError):
        validate_download_url(url)


def test_download_rejects_private_dns():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
        with pytest.raises(ValueError):
            validate_download_url("https://test.myqcloud.com/model.glb")
