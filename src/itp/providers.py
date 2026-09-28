import json
import re
from pathlib import Path

import httpx

from itp.config import Settings
from itp.preprocessing import image_base64

ACTIONS = {
    "geometry": ("SubmitHunyuanTo3DProJob", "QueryHunyuanTo3DProJob"),
    "topology": ("SubmitReduceFaceJob", "DescribeReduceFaceJob"),
    "texture": ("SubmitTextureTo3DJob", "DescribeTextureTo3DJob"),
    "rig": ("SubmitAutoRiggingJob", "DescribeAutoRiggingJob"),
}


class ProviderError(RuntimeError):
    pass


def safe_code(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "", str(value))[:100]


class TencentProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def call(self, action: str, payload: dict) -> dict:
        if not self.settings.geometry_ready:
            raise ProviderError("腾讯云 API 待配置")
        from tencentcloud.ai3d.v20250513 import ai3d_client, models
        from tencentcloud.common import credential
        from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
            TencentCloudSDKException,
        )
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile

        http = HttpProfile(endpoint=self.settings.tencent_endpoint, reqTimeout=60)
        profile = ClientProfile(httpProfile=http)
        profile.retryer = None
        client = ai3d_client.Ai3dClient(
            credential.Credential(
                self.settings.tencent_secret_id.get_secret_value(),
                self.settings.tencent_secret_key.get_secret_value(),
            ),
            self.settings.tencent_region,
            profile,
        )
        request = getattr(models, f"{action}Request")()
        request.from_json_string(json.dumps(payload))
        try:
            response = getattr(client, action)(request)
            return json.loads(response.to_json_string())
        except TencentCloudSDKException as exc:
            # Do not persist vendor messages that may contain signed URLs or request data.
            raise ProviderError(
                f"腾讯云错误 {safe_code(exc.get_code())}；"
                f"RequestId={safe_code(exc.get_request_id() or '')}"
            ) from None

    def submit(self, stage: str, payload: dict) -> dict:
        return self.call(ACTIONS[stage][0], payload)

    def query(self, stage: str, job_id: str) -> dict:
        return self.call(ACTIONS[stage][1], {"JobId": job_id})

    def convert(self, url: str) -> dict:
        result = self.call("Convert3DFormat", {"File3D": url, "Format": "FBX"})
        return {
            "results": [{"Type": "FBX", "Url": result["ResultFile3D"]}],
            "request_id": result.get("RequestId"),
        }


class PoseProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def edit(self, character: Path, reference: Path | None, mode: str, seed: int) -> dict:
        if not self.settings.pose_ready:
            raise ProviderError("姿势编辑 API 待配置")
        content = [{"image": image_base64(character, data_url=True)}]
        if reference:
            content.append({"image": image_base64(reference, data_url=True)})
            stance = "Match only the body pose and limb directions of the person in image 2."
        else:
            stance = (
                "Use a symmetric T-pose with both arms extended horizontally."
                if mode == "t-pose"
                else "Use a symmetric A-pose with arms angled down 45 degrees from the torso."
            )
        content.append(
            {
                "text": (
                    "Show one full-body character from image 1 on a plain white background. "
                    "Preserve identity, face, clothing, colors and proportions from image 1. "
                    f"{stance} Keep hands and feet in frame, separate limbs clearly. "
                    "Do not copy identity or clothing from image 2. "
                    "No captions, panels or extra people."
                )
            }
        )
        payload = {
            "model": self.settings.pose_model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": {
                "n": 1,
                "seed": seed,
                "watermark": False,
                "prompt_extend": False,
                "size": "1024*1024",
            },
        }
        with httpx.Client(timeout=180, trust_env=False) as client:
            response = client.post(
                self.settings.pose_endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.settings.pose_api_key.get_secret_value()}"
                },
            )
        if response.status_code != 200:
            raise ProviderError(f"姿势 API HTTP {response.status_code}；请在控制台核对权限与请求")
        data = response.json()
        if data.get("code"):
            raise ProviderError(f"姿势 API 错误 {safe_code(data['code'])}")
        try:
            result = data["output"]["choices"][0]["message"]["content"]
            url = next(item["image"] for item in result if "image" in item)
        except (KeyError, IndexError, StopIteration, TypeError) as exc:
            raise ProviderError("姿势 API 未返回图片") from exc
        return {"url": url, "request_id": data.get("request_id")}
