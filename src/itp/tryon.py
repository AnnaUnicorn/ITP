"""Durable six-view virtual try-on jobs backed by the mainland Ark image API."""

import base64
import binascii
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from itp.config import Settings
from itp.preprocessing import MAX_UPLOAD, image_base64, prepare_image
from itp.storage import Store

logger = logging.getLogger(__name__)
VIEWS = ("front", "back", "left", "right", "left_front", "right_front")
LABELS = ("正面", "背面", "左侧", "右侧", "左前45度", "右前45度")


class TryOnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="虚拟试穿", min_length=1, max_length=80)
    person: dict[str, str]
    garment: dict[str, str]
    consistent_confirmed: bool = False

    def validate_views(self):
        for group in (self.person, self.garment):
            if set(group) != set(VIEWS):
                raise ValueError("人物和衣服都需要上传完整六视图")
            if any(
                len(value) != 32 or any(char not in "0123456789abcdef" for char in value)
                for value in group.values()
            ):
                raise ValueError("图片资产 ID 无效")
        if not self.consistent_confirmed:
            raise ValueError("请确认各组六视图为同一对象、同一姿势和一致光照")


class TryOnStore:
    def __init__(self, root: Path):
        self.db = root / "tryons.sqlite3"
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tryons "
                "(id TEXT PRIMARY KEY, state TEXT, created REAL, document TEXT)"
            )

    def connect(self):
        return sqlite3.connect(self.db, timeout=10)

    def save(self, job: dict):
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tryons VALUES (?, ?, ?, ?)",
                (job["id"], job["state"], job["created"], json.dumps(job)),
            )

    def create(self, request: TryOnRequest, model: str) -> dict:
        job = {
            "id": uuid4().hex,
            "name": request.name,
            "created": time.time(),
            "state": "queued",
            "model": model,
            "request": request.model_dump(),
            "results": {},
            "active_view": None,
            "error": None,
        }
        self.save(job)
        return job

    def get(self, job_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT document FROM tryons WHERE id = ?", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT document FROM tryons ORDER BY created DESC LIMIT 100"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]


class SeedDreamProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=180, follow_redirects=False)

    def generate(self, image_paths: list[Path], prompt: str, model: str) -> bytes:
        if not self.settings.tryon_ready:
            raise RuntimeError("SeedDream API 尚未配置")
        payload = {
            "model": model,
            "prompt": prompt,
            "image": [image_base64(path, data_url=True) for path in image_paths],
            "size": "2K",
            "response_format": "b64_json",
            "watermark": False,
        }
        try:
            response = self.client.post(
                self.settings.seedream_endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.settings.seedream_api_key.get_secret_value()}"
                },
            )
            response.raise_for_status()
            data = response.json()["data"][0]["b64_json"]
            raw = base64.b64decode(data, validate=True)
        except (httpx.HTTPError, KeyError, IndexError, ValueError, binascii.Error) as exc:
            raise RuntimeError(
                f"SeedDream 生成失败（{type(exc).__name__}）；请检查服务配置和控制台任务记录"
            ) from None
        if len(raw) > MAX_UPLOAD:
            raise ValueError("SeedDream 返回图片超过 10 MiB")
        return raw


class TryOnWorker:
    def __init__(
        self,
        assets: Store,
        jobs: TryOnStore,
        settings: Settings,
        provider: SeedDreamProvider | None = None,
    ):
        self.assets, self.jobs, self.settings = assets, jobs, settings
        self.provider = provider or SeedDreamProvider(settings)
        self.stop = threading.Event()

    def run_job(self, job: dict):
        job["state"] = "running"
        self.jobs.save(job)
        try:
            for view, label in zip(VIEWS, LABELS, strict=True):
                if self.stop.is_set():
                    return
                if view in job["results"]:
                    continue
                job["active_view"] = view
                self.jobs.save(job)
                person = self.assets.path(job["request"]["person"][view])
                garment = self.assets.path(job["request"]["garment"][view])
                references = [person, garment]
                if view != "front":
                    references += [
                        self.assets.path(job["request"]["person"]["front"]),
                        self.assets.path(job["request"]["garment"]["front"]),
                        self.assets.path(job["results"]["front"]),
                    ]
                prompt = (
                    f"图1是人物{label}原图，图2是服装{label}原图。只替换人物衣服，输出同一人物的{label}全身照。"
                    "严格保留图1的身份、脸部五官、发型、肤色、体型、姿势、肢体数量、镜头角度和背景；"
                    "严格保留图2的服装版型、面料、纹样、颜色与细节，不改变服装结构。"
                    "光线真实，身体完整，不添加文字、道具或其他人物。"
                )
                if view != "front":
                    prompt += (
                        "图3是人物正面原图，图4是服装正面原图，图5是已经生成的换装正面图；"
                        "所有视角必须与图5为同一个人、同一套衣服。"
                    )
                # A crash during a billable request must not silently resubmit that view.
                job["state"] = "submitting"
                self.jobs.save(job)
                raw = self.provider.generate(references, prompt, job["model"])
                image = prepare_image(raw)
                asset_id, path = self.assets.new_asset_path("png")
                image.save(path, format="PNG")
                self.assets.add_asset(
                    asset_id, path, "image", width=image.width, height=image.height
                )
                job["results"][view] = asset_id
                job["state"] = "running"
                self.jobs.save(job)
            job["state"] = "ready"
            job["active_view"] = None
            self.jobs.save(job)
        except Exception as exc:
            job["state"] = "failed"
            job["error"] = (
                str(exc) if isinstance(exc, (RuntimeError, ValueError)) else "虚拟试穿处理失败"
            )
            self.jobs.save(job)
            logger.warning("Try-on %s failed (%s)", job["id"], type(exc).__name__)

    def run_forever(self):
        for job in self.jobs.list():
            if job["state"] in {"running", "submitting"}:
                job["state"] = "failed"
                job["error"] = "进程中断时云端结果不确定；未自动重提，请核对控制台后重新创建任务"
                self.jobs.save(job)
        while not self.stop.is_set():
            for job in self.jobs.list():
                if job["state"] == "queued":
                    self.run_job(job)
            self.stop.wait(0.5)
