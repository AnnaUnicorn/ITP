"""Load official FLUX.2 Klein 4B or 9B weights for multi-reference editing."""

import io
import logging
import os
import threading
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)
DEFAULT_MODEL_NAME = "flux.2-klein-4b"
MODEL_REPOSITORIES = {
    "flux.2-klein-4b": "black-forest-labs/FLUX.2-klein-4B",
    "flux.2-klein-9b": "black-forest-labs/FLUX.2-klein-9B",
}
MODEL_ARCHITECTURES = {
    "flux.2-klein-4b": {
        "num_attention_heads": 24, "num_layers": 5,
        "num_single_layers": 20, "joint_attention_dim": 7680,
    },
    "flux.2-klein-9b": {
        "num_attention_heads": 32, "num_layers": 8,
        "num_single_layers": 24, "joint_attention_dim": 12288,
    },
}


def validate_model_config(model_name: str, config: dict) -> None:
    """Reject the wrong model size before allocating its weights."""
    if model_name not in MODEL_ARCHITECTURES:
        raise ValueError("ITP_KLEIN_MODEL_ID must be flux.2-klein-4b or flux.2-klein-9b")
    expected = MODEL_ARCHITECTURES[model_name]
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError(f"Transformer configuration does not match {model_name}")


class KleinEngine:
    def __init__(self, pipe, device: str, model_name: str = DEFAULT_MODEL_NAME):
        self.pipe = pipe
        self.device = device
        self.model_name = model_name
        self.lock = threading.Lock()

    @classmethod
    def load(cls, model_name: str = DEFAULT_MODEL_NAME):
        import torch
        from diffusers import Flux2KleinPipeline, Flux2Transformer2DModel

        if model_name not in MODEL_REPOSITORIES:
            raise ValueError("ITP_KLEIN_MODEL_ID must be flux.2-klein-4b or flux.2-klein-9b")
        offload = os.environ.get("ITP_KLEIN_OFFLOAD", "sequential").lower()
        if offload not in {"model", "sequential", "none"}:
            raise RuntimeError("ITP_KLEIN_OFFLOAD must be model, sequential, or none")
        if not torch.cuda.is_available():
            raise RuntimeError(f"CUDA GPU is required for {model_name}")
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
            model_path = MODEL_REPOSITORIES[model_name]
        config = Flux2Transformer2DModel.load_config(model_path, subfolder="transformer")
        validate_model_config(model_name, config)
        logger.info("Loading %s on %s", model_path, device)
        pipe = Flux2KleinPipeline.from_pretrained(model_path, torch_dtype=torch.bfloat16)
        if offload == "model":
            pipe.enable_model_cpu_offload(gpu_id=gpu)
        elif offload == "sequential":
            pipe.enable_sequential_cpu_offload(gpu_id=gpu)
        elif offload == "none":
            pipe.to(device)
        logger.info("%s loaded; offload=%s", model_name, offload)
        return cls(pipe, device, model_name)

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
