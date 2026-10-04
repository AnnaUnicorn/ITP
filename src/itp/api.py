import asyncio
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock, Timeout
from pydantic import BaseModel, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from itp.config import Settings
from itp.face_refine import (
    FaceRefineRequest,
    FaceRefineStore,
    FaceRefineWorker,
    prepare_face_photo,
)
from itp.pipeline import Pipeline
from itp.preprocessing import MAX_UPLOAD, Segmenter, image_base64, prepare_image
from itp.provider_settings import (
    ProviderSettingsUpdate,
    public_provider_settings,
    save_provider_settings,
    validate_provider_update,
)
from itp.schemas import JobRequest
from itp.storage import Store, public_asset, public_job
from itp.tryon import VIEWS, TryOnRequest, TryOnStore, TryOnWorker


class ReviewRequest(BaseModel):
    approve: bool


def create_app(
    settings: Settings | None = None,
    *,
    start_worker: bool = True,
    config_path: Path = Path(".env"),
) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.data_dir)
    segmenter = Segmenter(settings.segmentation_model)
    pipeline = Pipeline(store, settings)
    tryons = TryOnStore(store.root)
    tryon_worker = TryOnWorker(store, tryons, settings)
    face_jobs = FaceRefineStore(store.root)
    face_worker = FaceRefineWorker(store, face_jobs, settings)
    settings_lock = threading.Lock()
    face_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        lock = FileLock(str(store.root / "worker.lock"))
        thread = None
        tryon_thread = None
        face_thread = None
        if start_worker:
            try:
                lock.acquire(timeout=0)
            except Timeout as exc:
                raise RuntimeError(
                    "ITP already uses this data directory; run one worker only"
                ) from exc
            thread = threading.Thread(target=pipeline.run_forever, daemon=True, name="itp-worker")
            thread.start()
            tryon_thread = threading.Thread(
                target=tryon_worker.run_forever, daemon=True, name="itp-tryon-worker"
            )
            tryon_thread.start()
            face_thread = threading.Thread(
                target=face_worker.run_forever, daemon=True, name="itp-face-worker"
            )
            face_thread.start()
        try:
            yield
        finally:
            if thread:
                pipeline.stop.set()
                tryon_worker.stop.set()
                face_worker.stop.set()
                await asyncio.to_thread(thread.join)
                await asyncio.to_thread(tryon_thread.join)
                await asyncio.to_thread(face_thread.join)
                lock.release()

    app = FastAPI(title="ITP Studio API", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.pipeline = pipeline
    app.state.tryons = tryons
    app.state.tryon_worker = tryon_worker
    app.state.face_jobs = face_jobs
    app.state.face_worker = face_worker
    app.state.settings = settings
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])

    def flux_klein_health() -> dict:
        current = app.state.settings
        if not current.tryon_provider_ready("flux_klein"):
            return {"ready": False, "model": current.flux_klein_model}
        url = current.flux_klein_endpoint.removesuffix("/v1/flux-klein/edit") + "/health"
        try:
            with httpx.Client(timeout=3, follow_redirects=False, trust_env=False) as client:
                response = client.get(url, headers={
                    "Authorization": f"Bearer {current.flux_klein_api_key.get_secret_value()}"
                })
                response.raise_for_status()
                body = response.json()
                ready = body.get("ready") is True and body.get("model") == current.flux_klein_model
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            ready = False
        return {"ready": ready, "model": current.flux_klein_model}

    @app.exception_handler(RequestValidationError)
    async def redact_settings_validation(request: Request, exc: RequestValidationError):
        if request.url.path == "/api/settings":
            return JSONResponse({"detail": "配置项无效，请检查输入内容"}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        origin = request.headers.get("origin")
        allowed = {
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        }
        if request.headers.get("host"):
            allowed.add(f"{request.url.scheme}://{request.headers['host']}")
        if app.state.settings.public_origin:
            allowed.add(app.state.settings.public_origin)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in allowed:
            return JSONResponse({"detail": "仅允许本地工作台请求"}, status_code=403)
        # Normal browser uploads include Content-Length; route code also bounds the actual image.
        size = request.headers.get("content-length")
        upload_paths = {"/api/assets", "/api/face-photos"}
        if request.method == "POST" and request.url.path in upload_paths and size is None:
            return JSONResponse({"detail": "上传图片需要 Content-Length 请求头"}, status_code=411)
        if size and (not size.isdigit() or int(size) > MAX_UPLOAD + 65536):
            return JSONResponse({"detail": "请求体过大或长度无效"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path == "/api/settings":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/capabilities")
    def capabilities():
        current = app.state.settings
        return {
            "geometry": current.geometry_ready,
            "pose": current.pose_ready,
            "tryon": current.tryon_ready,
            "tryon_model": current.seedream_model,
            "tryon_providers": {
                name: current.tryon_provider_ready(name)
                for name in ("seedream", "flux", "flux_klein", "gpt_image")
            },
            "faceverse": current.faceverse_ready,
            "faceverse_model": current.faceverse_model,
            "segmentation": current.segmentation_model.is_file(),
            "provider": "腾讯云混元 AI3D（国内）",
            "pose_provider": "千问图像编辑（国内）",
            "model": current.tencent_model,
            "pose_model": current.pose_model,
            "max_upload_mb": 10,
        }

    @app.get("/api/tryon-providers/flux-klein/health")
    def get_flux_klein_health():
        return flux_klein_health()

    @app.get("/api/settings")
    def get_provider_settings():
        return public_provider_settings(app.state.settings)

    @app.patch("/api/settings")
    def update_provider_settings(body: ProviderSettingsUpdate):
        with settings_lock:
            try:
                updated, changes = validate_provider_update(app.state.settings, body)
            except (ValueError, ValidationError) as exc:
                raise HTTPException(422, "配置项无效，请检查服务地址和输入内容") from exc
            if any(f"ITP_{field.upper()}" in os.environ for field in changes):
                raise HTTPException(409, "该配置已由进程环境变量指定，请在启动环境中修改")
            try:
                save_provider_settings(config_path, changes)
            except OSError as exc:
                raise HTTPException(500, "无法保存配置文件，请检查文件权限") from exc
            app.state.settings = updated
            pipeline.settings = updated
            pipeline.cloud.settings = updated
            pipeline.pose.settings = updated
            tryon_worker.settings = updated
            tryon_worker.provider.settings = updated
            for provider in tryon_worker.providers.values():
                provider.settings = updated
            face_worker.settings = updated
            face_worker.provider.settings = updated
            return public_provider_settings(updated)

    @app.post("/api/assets", status_code=201)
    async def upload(file: UploadFile = File(...), remove_background: bool = Query(False)):
        try:
            data = await file.read(MAX_UPLOAD + 1)
        finally:
            await file.close()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "图片不能超过 10 MiB")
        if remove_background and not app.state.settings.segmentation_model.is_file():
            raise HTTPException(503, "去背景权重尚未安装")
        try:
            image = await asyncio.to_thread(
                prepare_image, data, segmenter if remove_background else None
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        asset_id, path = store.new_asset_path("png")
        image.save(path, format="PNG")
        asset = store.add_asset(
            asset_id,
            path,
            "image",
            width=image.width,
            height=image.height,
            background_removed=remove_background,
        )
        return public_asset(asset)

    @app.post("/api/face-photos", status_code=201)
    async def upload_face_photo(file: UploadFile = File(...)):
        try:
            data = await file.read(MAX_UPLOAD + 1)
        finally:
            await file.close()
        try:
            image = await asyncio.to_thread(prepare_face_photo, data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        asset_id, path = store.new_asset_path("png")
        image.save(path, format="PNG")
        return public_asset(store.add_asset(
            asset_id, path, "face_photo", width=image.width, height=image.height
        ))

    @app.get("/api/assets/{asset_id}")
    def get_asset(asset_id: str):
        asset = store.asset(asset_id)
        if not asset:
            raise HTTPException(404, "资产不存在")
        return public_asset(asset)

    @app.get("/api/assets/{asset_id}/file")
    def get_file(asset_id: str, download: bool = False):
        asset = store.asset(asset_id)
        if not asset:
            raise HTTPException(404, "资产不存在")
        path = store.path(asset_id)
        if not path.is_file():
            raise HTTPException(404, "资产文件已丢失")
        media = {"GLB": "model/gltf-binary", "PNG": "image/png"}.get(
            asset.get("format", "PNG"), "application/octet-stream"
        )
        return FileResponse(path, media_type=media, filename=path.name if download else None)

    @app.get("/api/jobs")
    def list_jobs():
        return [public_job(j) for j in store.jobs()]

    @app.post("/api/jobs", status_code=201)
    def create_job(body: JobRequest):
        ids = [body.front, *body.views.values()]
        if body.pose_reference:
            ids.append(body.pose_reference)
        for asset_id in ids:
            asset = store.asset(asset_id)
            if not asset or asset["kind"] != "image" or not store.path(asset_id).is_file():
                raise HTTPException(422, "输入图片不存在，请重新上传")
        current = app.state.settings
        if current.tencent_model == "3.0" and any(
            view in body.views for view in ("left_front", "right_front")
        ):
            raise HTTPException(422, "左前/右前视图需要腾讯云混元 3D 3.1")
        encoded_total = sum(
            len(image_base64(store.path(asset_id)))
            for asset_id in [body.front, *body.views.values()]
        )
        if encoded_total > 8 * 1024 * 1024:
            raise HTTPException(422, "多视图图片编码后超过腾讯云 8 MiB 限制，请压缩后重试")
        if not current.geometry_ready:
            raise HTTPException(503, "腾讯云 API 待配置；请在设置页填写")
        if body.pose_mode != "original" and not current.pose_ready:
            raise HTTPException(503, "姿势编辑 API 待配置；请在设置页填写")
        models = {"geometry": current.tencent_model}
        if body.pose_mode != "original":
            models["pose"] = current.pose_model
        return public_job(store.create_job(body.model_dump(), models=models))

    @app.get("/api/tryons")
    def list_tryons():
        return tryons.list()

    @app.post("/api/tryons", status_code=201)
    def create_tryon(body: TryOnRequest):
        try:
            body.validate_views()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        for asset_id in [*body.person.values(), *body.garment.values()]:
            asset = store.asset(asset_id)
            if not asset or asset["kind"] != "image" or not store.path(asset_id).is_file():
                raise HTTPException(422, "输入图片不存在，请重新上传")
        if not app.state.settings.tryon_provider_ready(body.provider):
            raise HTTPException(503, "所选生图模型 API 待配置；请在设置页填写")
        if body.provider == "flux_klein" and not flux_klein_health()["ready"]:
            raise HTTPException(503, "FLUX.2 Klein 4B 服务尚未就绪；请检查健康状态")
        return tryons.create(body, app.state.settings.tryon_model_for(body.provider))

    @app.get("/api/tryons/{tryon_id}")
    def get_tryon(tryon_id: str):
        job = tryons.get(tryon_id)
        if not job:
            raise HTTPException(404, "试穿任务不存在")
        return job

    @app.post("/api/tryons/{tryon_id}/continue", status_code=201)
    def continue_tryon(tryon_id: str):
        tryon = tryons.get(tryon_id)
        if not tryon:
            raise HTTPException(404, "试穿任务不存在")
        if tryon["state"] != "ready" or set(tryon["results"]) != set(VIEWS):
            raise HTTPException(409, "六张试穿结果尚未生成完成")
        current = app.state.settings
        if not current.geometry_ready:
            raise HTTPException(503, "腾讯云 API 待配置；请在设置页填写")
        results = tryon["results"]
        request = JobRequest(name=tryon["name"], front=results["front"],
                             views={view: results[view] for view in VIEWS if view != "front"},
                             views_consistent_confirmed=True)
        return public_job(store.create_job(request.model_dump()))

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = store.job(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        return public_job(job)

    @app.get("/api/jobs/{job_id}/face-refinement")
    def get_face_refinements(job_id: str):
        if not store.job(job_id):
            raise HTTPException(404, "任务不存在")
        return face_jobs.for_job(job_id)

    @app.post("/api/jobs/{job_id}/face-refinement", status_code=201)
    def create_face_refinement(job_id: str, body: FaceRefineRequest):
        source = store.job(job_id)
        if not source:
            raise HTTPException(404, "任务不存在")
        if source["state"] != "succeeded":
            raise HTTPException(409, "请等待 3D 模型生成完成")
        photo = store.asset(body.face_photo)
        if not photo or photo["kind"] != "face_photo" or not store.path(body.face_photo).is_file():
            raise HTTPException(422, "请上传原始高清正面人物照片")
        if not app.state.settings.faceverse_ready:
            raise HTTPException(503, "FaceVerse 服务器待配置；请在设置页填写")
        meshes = [artifact for artifact in source["artifacts"]
                  if artifact["format"] == "GLB" and artifact["stage"] != "face_refine"]
        if not meshes:
            raise HTTPException(409, "当前任务尚无可精修的 GLB 模型")
        with face_lock:
            if any(item["state"] in {"queued", "running", "submitting"}
                   for item in face_jobs.for_job(job_id)):
                raise HTTPException(409, "该模型已有进行中的脸部精修任务")
            return face_jobs.create(job_id, body.face_photo, meshes[-1]["asset_id"],
                                    app.state.settings.faceverse_model)

    @app.post("/api/jobs/{job_id}/review")
    def review_job(job_id: str, body: ReviewRequest):
        if body.approve and not app.state.settings.geometry_ready:
            raise HTTPException(503, "腾讯云 API 待配置，不能继续生成")
        try:
            return public_job(store.review(job_id, body.approve))
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    else:

        @app.get("/")
        def index():
            return {
                "message": "ITP API ready. Build frontend to serve the workspace.",
                "docs": "/docs",
            }

    return app
