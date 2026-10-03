"""Load official FLUX.2 Klein 4B weights and run multi-reference editing."""

import io
import logging
import os
import threading
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)
MODEL_ID = "black-forest-labs/FLUX.2-klein-4B"


class KleinEngine:
    def __init__(self, pipe, device: str):
        self.pipe = pipe
        self.device = device
        self.lock = threading.Lock()

    @classmethod
    def load(cls):
        import torch
        from diffusers import Flux2KleinPipeline

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU is required for FLUX.2 Klein 4B")
        gpu = int(os.environ.get("ITP_KLEIN_GPU", "0"))
        if gpu < 0 or gpu >= torch.cuda.device_count():
            raise RuntimeError("ITP_KLEIN_GPU is not an available CUDA device")
        torch.cuda.set_device(gpu)
        device = f"cuda:{gpu}"
        model_path = os.environ.get("ITP_KLEIN_MODEL_PATH", "")
        if model_path:
            if not Path(model_path).is_absolute() or not Path(model_path).is_dir():
                raise RuntimeError("ITP_KLEIN_MODEL_PATH must be an existing absolute directory")
        else:
            model_path = MODEL_ID
        logger.info("Loading %s on %s", model_path, device)
        pipe = Flux2KleinPipeline.from_pretrained(model_path, torch_dtype=torch.bfloat16)
        offload = os.environ.get("ITP_KLEIN_OFFLOAD", "sequential").lower()
        if offload == "model":
            pipe.enable_model_cpu_offload(gpu_id=gpu)
        elif offload == "sequential":
            pipe.enable_sequential_cpu_offload(gpu_id=gpu)
        elif offload == "none":
            pipe.to(device)
        else:
            raise RuntimeError("ITP_KLEIN_OFFLOAD must be model, sequential, or none")
        logger.info("FLUX.2 Klein 4B loaded; offload=%s", offload)
        return cls(pipe, device)

    def edit(self, images: list[Image.Image], prompt: str) -> bytes:
        import torch

        if not 1 <= len(images) <= 4:
            raise ValueError("1 to 4 reference images are required")
        with self.lock, torch.inference_mode():
            output = self.pipe(
                image=images,
                prompt=prompt,
                height=1024,
                width=768,
                guidance_scale=1.0,
                num_inference_steps=4,
            ).images[0]
            stream = io.BytesIO()
            output.save(stream, format="PNG")
            return stream.getvalue()
