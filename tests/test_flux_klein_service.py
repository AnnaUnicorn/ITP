import base64

import pytest
from pydantic import ValidationError

from services.flux_klein.itp_flux_klein_service.api import EditRequest, decode_image


def test_flux_klein_service_decodes_real_image(image_bytes):
    encoded = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    image = decode_image(encoded)
    assert image.mode == "RGB"
    assert image.size == (256, 256)
    request = EditRequest(prompt="Change clothing", images=[encoded])
    assert request.model == "flux.2-klein-4b"


def test_flux_klein_service_rejects_invalid_references(image_bytes):
    encoded = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    with pytest.raises(ValidationError):
        EditRequest(prompt="test", images=[encoded] * 5)
    with pytest.raises(ValueError):
        decode_image("data:image/png;base64,not-valid-base64")
