from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ITP_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    segmentation_model: Path = Path("models/u2netp.onnx")
    tencent_endpoint: str = ""
    tencent_secret_id: SecretStr = SecretStr("")
    tencent_secret_key: SecretStr = SecretStr("")
    tencent_region: str = ""
    tencent_model: str = "3.1"
    pose_endpoint: str = ""
    pose_api_key: SecretStr = SecretStr("")
    pose_model: str = "qwen-image-edit-plus-2025-12-15"
    seedream_endpoint: str = ""
    seedream_api_key: SecretStr = SecretStr("")
    seedream_model: str = "doubao-seedream-5-0-flash-260915"
    faceverse_endpoint: str = ""
    faceverse_api_key: SecretStr = SecretStr("")
    faceverse_model: str = "faceverse-v4"
    poll_seconds: float = Field(default=5, ge=0.05)
    task_timeout_seconds: int = Field(default=3600, ge=30)

    @model_validator(mode="after")
    def validate_endpoints(self):
        if self.tencent_endpoint and self.tencent_endpoint != "ai3d.tencentcloudapi.com":
            raise ValueError("Tencent endpoint must be the mainland AI3D hostname")
        if self.pose_endpoint:
            url = urlparse(self.pose_endpoint)
            host = url.hostname or ""
            allowed = host == "dashscope.aliyuncs.com" or host.endswith(
                ".cn-beijing.maas.aliyuncs.com"
            )
            if (
                not allowed
                or url.scheme != "https"
                or url.username
                or url.password
                or url.port not in (None, 443)
                or url.query
                or url.fragment
                or url.path != "/api/v1/services/aigc/multimodal-generation/generation"
            ):
                raise ValueError("Pose endpoint must be a mainland Model Studio generation URL")
        if self.seedream_endpoint and self.seedream_endpoint != "https://ark.cn-beijing.volces.com/api/v3/images/generations":
            raise ValueError("Seedream endpoint must be the mainland Ark image generations URL")
        if self.faceverse_endpoint:
            url = urlparse(self.faceverse_endpoint)
            if (
                url.scheme not in {"https", "http"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path != "/v1/face-refine"
                or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})
            ):
                raise ValueError(
                    "FaceVerse endpoint must be HTTPS or a local HTTP /v1/face-refine URL"
                )
        return self

    @property
    def geometry_ready(self) -> bool:
        return all(
            (
                self.tencent_endpoint,
                self.tencent_region,
                self.tencent_secret_id.get_secret_value(),
                self.tencent_secret_key.get_secret_value(),
            )
        )

    @property
    def pose_ready(self) -> bool:
        return bool(self.pose_endpoint and self.pose_api_key.get_secret_value())

    @property
    def tryon_ready(self) -> bool:
        return bool(self.seedream_endpoint and self.seedream_api_key.get_secret_value())

    @property
    def faceverse_ready(self) -> bool:
        return bool(self.faceverse_endpoint)
