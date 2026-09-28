import base64
import hashlib
import io
import threading
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

MODEL_MD5 = "8e83ca70e441ab06c318d82300c84806"
MAX_UPLOAD = 10 * 1024 * 1024
MAX_PIXELS = 25_000_000


class Segmenter:
    def __init__(self, path: Path):
        self.path = path
        self._session = None
        self._lock = threading.Lock()

    def remove(self, image: Image.Image) -> Image.Image:
        with self._lock:
            if self._session is None:
                if not self.path.is_file():
                    raise ValueError("去背景权重尚未安装，请运行权重下载脚本")
                if hashlib.md5(self.path.read_bytes()).hexdigest() != MODEL_MD5:
                    raise ValueError("去背景权重校验失败")
                import onnxruntime as ort

                options = ort.SessionOptions()
                options.intra_op_num_threads = 2
                self._session = ort.InferenceSession(
                    str(self.path), sess_options=options, providers=["CPUExecutionProvider"]
                )
            rgb = image.convert("RGB").resize((320, 320), Image.Resampling.LANCZOS)
            pixels = np.asarray(rgb, dtype=np.float32)
            pixels /= max(float(pixels.max()), 1e-6)
            pixels = (pixels - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
            tensor = pixels.transpose(2, 0, 1)[None].astype(np.float32)
            prediction = self._session.run(None, {self._session.get_inputs()[0].name: tensor})[0]
            mask = prediction[0, 0]
            mask = (mask - mask.min()) / max(float(np.ptp(mask)), 1e-6)
            alpha = Image.fromarray((mask * 255).astype(np.uint8)).resize(
                image.size, Image.Resampling.LANCZOS
            )
            result = image.convert("RGBA")
            combined = np.minimum(np.asarray(result.getchannel("A")), np.asarray(alpha))
            result.putalpha(Image.fromarray(combined))
            return result


def prepare_image(data: bytes, segmenter: Segmenter | None = None) -> Image.Image:
    if len(data) > MAX_UPLOAD:
        raise ValueError("图片不能超过 10 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("仅支持 PNG、JPEG、WebP")
                if min(source.size) < 128 or source.width * source.height > MAX_PIXELS:
                    raise ValueError("图片短边至少 128 像素，总像素不能超过 2500 万")
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("不支持动态图像")
                image = ImageOps.exif_transpose(source).convert("RGBA")
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("图片损坏、格式不支持或尺寸过大") from exc
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    if min(image.size) < 129:
        raise ValueError("图片长宽比过大，缩放后短边不足 129 像素")
    image.info.clear()
    return segmenter.remove(image) if segmenter else image


def image_base64(path: Path, *, data_url: bool = False) -> str:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        rgb = Image.new("RGB", image.size, "white")
        rgb.paste(rgba, mask=rgba.getchannel("A"))
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=92)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}" if data_url else encoded
