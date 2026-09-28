from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="未命名资产", min_length=1, max_length=80)
    front: str = Field(pattern=r"^[a-f0-9]{32}$")
    views: dict[Literal["left", "right", "back"], str] = Field(default_factory=dict)
    pose_mode: Literal["original", "custom", "a-pose", "t-pose"] = "original"
    pose_reference: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    topology: bool = False
    polygon_type: Literal["triangle", "quadrilateral"] = "triangle"
    face_level: Literal["low", "medium", "high"] = "medium"
    face_count: int = Field(default=100000, ge=3000, le=1500000)
    texture: bool = True
    texture_size: Literal[1024, 2048, 4096] = 2048
    rig: bool = False
    neutral_pose_confirmed: bool = False
    export_fbx: bool = False
    seed: int = Field(default=42, ge=0, le=2147483647)

    @model_validator(mode="after")
    def validate_combination(self):
        if self.pose_mode == "custom" and not self.pose_reference:
            raise ValueError("自定义姿势需要姿势参考图")
        if self.pose_mode != "custom" and self.pose_reference:
            raise ValueError("只有自定义姿势模式接受姿势参考图")
        if self.pose_mode != "original" and self.views:
            raise ValueError("姿势变换不能混用原姿势的多视角图片")
        if self.rig and (self.pose_mode == "custom" or not self.neutral_pose_confirmed):
            raise ValueError("自动绑骨要求已确认的 A/T 中性姿态，不能使用动态自定义姿势")
        return self
