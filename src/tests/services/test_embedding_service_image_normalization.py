import base64
import io
from unittest.mock import MagicMock

from PIL import Image

from iatoolkit.services.embedding_service import HuggingFaceClientWrapper


def test_huggingface_wrapper_normalizes_grayscale_image_bytes_before_request():
    inference_service = MagicMock()
    inference_service.predict.return_value = {"embedding": [0.1, 0.2]}

    wrapper = HuggingFaceClientWrapper(
        client=None,
        model="openai/clip-vit-base-patch32",
        inference_service=inference_service,
        company_short_name="acme",
        tool_name="clip_embeddings",
    )

    buffer = io.BytesIO()
    Image.new("L", (3, 3), color=128).save(buffer, format="PNG")

    result = wrapper.get_image_embedding(
        presigned_url="https://example.com/raw-grayscale.png",
        image_bytes=buffer.getvalue(),
    )

    assert result == [0.1, 0.2]
    inference_service.predict.assert_called_once()

    call_args = inference_service.predict.call_args[0]
    assert call_args[0] == "acme"
    assert call_args[1] == "clip_embeddings"
    assert "url" not in call_args[2]

    normalized_bytes = base64.b64decode(call_args[2]["base64"])
    with Image.open(io.BytesIO(normalized_bytes)) as normalized_image:
        assert normalized_image.mode == "RGB"
