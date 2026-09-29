from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from itp.preprocessing import Segmenter


def test_local_u2netp_weight_runs_cpu_inference():
    model = Path(__file__).resolve().parents[1] / "models" / "u2netp.onnx"
    if not model.is_file():
        pytest.skip("Optional local model has not been installed")
    image = Image.new("RGBA", (256, 256), (240, 240, 240, 255))
    for x in range(70, 180):
        for y in range(45, 230):
            image.putpixel((x, y), (90, 50, 190, 255))
    result = Segmenter(model).remove(image)
    alpha = np.asarray(result.getchannel("A"))
    assert result.size == image.size
    assert alpha.shape == (256, 256)
    assert alpha.dtype == np.uint8
