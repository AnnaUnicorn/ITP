"""Bearer-protected FastAPI contract for FLUX.2 Klein 4B editing."""

import base64
import binascii
import io
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from .inference import KleinEngine

logger = logging.getLogger(__name__)
MODEL_NAME = "flux.2-klein-4b"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_BODY_BYTES = 56 * 1024 * 1024
MAX_PIXELS = 25_000_000


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = MODEL_NAME
    prompt: str = Field(min_length=1, max_length=16000)
    images: list[str] = Field(min_length=1, max_length=4)


def decode_image(value: str) -> Image.Image:
    if not value.startswith("data:image/") or ";base64," not in value:
        raise ValueError("Image must be a base64 data URL")
    header, encoded = value.split(",", 1)
    if header not in {"data:image/png;base64", "data:image/jpeg;base64", "data:image/webp;base64"}:
        raise ValueError("Only PNG, JPEG and WebP images are supported")
    if len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 8:
        raise ValueError("Reference image is too large")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Reference image is too large")
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Unsupported image format")
            if min(source.size) < 128 or source.width * source.height > MAX_PIXELS:
                raise ValueError("Reference image dimensions are invalid")
            return ImageOps.exif_transpose(source).convert("RGB")
    except (binascii.Error, UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ValueError("Reference image could not be decoded") from exc


def create_app(engine: KleinEngine | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.engine is None:
            try:
                app.state.engine = KleinEngine.load()
                app.state.load_error = None
            except Exception as exc:
                app.state.load_error = type(exc).__name__
                logger.exception("FLUX.2 Klein 4B failed to load")
        yield

    app = FastAPI(title="ITP FLUX.2 Klein 4B Service", lifespan=lifespan)
    app.state.engine = engine
    app.state.load_error = None

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        if request.method == "POST":
            size = request.headers.get("content-length")
            if size is None:
                return JSONResponse({"detail": "Content-Length is required"}, status_code=411)
            if not size.isdigit() or int(size) > MAX_BODY_BYTES:
                return JSONResponse({"detail": "Request body is too large"}, status_code=413)
        return await call_next(request)

    def authorize(authorization: str | None = Header(default=None)):
        import hmac

        token = os.environ.get("ITP_KLEIN_API_TOKEN", "")
        if not token or not authorization or not hmac.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(401, "Bearer token is required")

    @app.get("/health")
    def health():
        return {"ready": app.state.engine is not None, "model": MODEL_NAME,
                "error": app.state.load_error}

    @app.post("/v1/flux-klein/edit", dependencies=[Depends(authorize)])
    def edit(body: EditRequest):
        if body.model != MODEL_NAME:
            raise HTTPException(422, "Unsupported model")
        if app.state.engine is None:
            raise HTTPException(503, "Model is not loaded")
        try:
            images = [decode_image(value) for value in body.images]
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            result = app.state.engine.edit(images, body.prompt)
        except Exception as exc:
            logger.exception("FLUX.2 Klein 4B inference failed")
            if "out of memory" in str(exc).lower():
                raise HTTPException(507, "GPU out of memory") from exc
            raise HTTPException(500, "Image generation failed") from exc
        if len(result) > MAX_IMAGE_BYTES:
            raise HTTPException(500, "Generated image exceeds output limit")
        return {"model": MODEL_NAME, "data": [{"b64_json": base64.b64encode(result).decode("ascii")}]}

    return app


app = create_app()
