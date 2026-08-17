import base64
import importlib
import io
import sys
import types
from unittest.mock import MagicMock

import pytest
from PIL import Image

# torch arrives with the optional `inference` extra, and most installs will not
# have it: the only thing that needs it is `infra/inference_handler`, which
# nothing in the source imports — this test reaches it by importlib.
#
# A bare `import torch` here was not a failing test, it was an uncollectable
# module, and CI runs with --maxfail=1: two skippable tests aborted the entire
# suite. Skipping is the same contract test_docling_service.py already uses for
# its own extra.
torch = pytest.importorskip("torch")


class ProcessorInputs(dict):
    def to(self, _device):
        return self


def _load_endpoint_handler(monkeypatch):
    diffusers_module = types.SimpleNamespace(
        DiffusionPipeline=MagicMock(),
        DPMSolverMultistepScheduler=MagicMock(),
    )
    diffusers_utils_module = types.SimpleNamespace(export_to_video=MagicMock())
    transformers_module = types.SimpleNamespace(
        CLIPProcessor=MagicMock(),
        CLIPModel=MagicMock(),
        AutoTokenizer=MagicMock(),
        AutoModel=MagicMock(),
        pipeline=MagicMock(),
    )

    monkeypatch.setitem(sys.modules, "diffusers", diffusers_module)
    monkeypatch.setitem(sys.modules, "diffusers.utils", diffusers_utils_module)
    monkeypatch.setitem(sys.modules, "transformers", transformers_module)
    sys.modules.pop("iatoolkit.infra.inference_handler", None)
    module = importlib.import_module("iatoolkit.infra.inference_handler")
    return module.EndpointHandler


def test_clip_handler_converts_grayscale_base64_image_to_rgb_before_processing(monkeypatch):
    previous_module = sys.modules.get("iatoolkit.infra.inference_handler")
    try:
        EndpointHandler = _load_endpoint_handler(monkeypatch)
        handler = EndpointHandler()
        handler.device = "cpu"
        handler.processor_instance = MagicMock()
        handler.model_instance = MagicMock()

        captured_images = []

        def processor_side_effect(*, images, return_tensors):
            captured_images.append(images)
            assert return_tensors == "pt"
            return ProcessorInputs(pixel_values=torch.zeros((1, 3, 2, 2)))

        handler.processor_instance.side_effect = processor_side_effect
        handler.model_instance.get_image_features.return_value = torch.tensor([[1.0, 0.0]])

        buffer = io.BytesIO()
        Image.new("L", (2, 2), color=128).save(buffer, format="PNG")
        image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        result = handler._handle_clip({"mode": "image", "base64": image_base64})

        assert result == {"embedding": [1.0, 0.0]}
        assert captured_images[0].mode == "RGB"
    finally:
        sys.modules.pop("iatoolkit.infra.inference_handler", None)
        if previous_module is not None:
            sys.modules["iatoolkit.infra.inference_handler"] = previous_module


def test_text_embedding_handler_answers_both_single_and_batch_shapes(monkeypatch):
    """The endpoint must keep serving callers that predate inputs.texts."""
    previous_module = sys.modules.get("iatoolkit.infra.inference_handler")
    try:
        EndpointHandler = _load_endpoint_handler(monkeypatch)

        def _tokenizer(texts, padding=True, truncation=True, return_tensors="pt"):
            count = len(texts) if isinstance(texts, list) else 1
            return ProcessorInputs(
                input_ids=torch.ones((count, 3), dtype=torch.long),
                attention_mask=torch.ones((count, 3), dtype=torch.long),
            )

        def _model(**kwargs):
            rows = kwargs["input_ids"].shape[0]
            return (torch.arange(rows * 3 * 4, dtype=torch.float).reshape(rows, 3, 4),)

        handler = EndpointHandler.__new__(EndpointHandler)
        handler.device = "cpu"
        handler.processor_instance = _tokenizer
        handler.model_instance = _model

        single = handler._handle_text_embedding({"text": "hola"})
        assert set(single) == {"embedding"}
        assert len(single["embedding"]) == 4

        batch = handler._handle_text_embedding({"texts": ["hola", "chau", "que tal"]})
        assert set(batch) == {"embeddings"}
        assert len(batch["embeddings"]) == 3
        assert len(batch["embeddings"][0]) == 4

        # A one-element batch must resolve to the same vector as the single path.
        one = handler._handle_text_embedding({"texts": ["hola"]})
        assert one["embeddings"][0] == pytest.approx(single["embedding"])

        with pytest.raises(ValueError, match="non-empty list"):
            handler._handle_text_embedding({"texts": []})
    finally:
        if previous_module is not None:
            sys.modules["iatoolkit.infra.inference_handler"] = previous_module
        else:
            sys.modules.pop("iatoolkit.infra.inference_handler", None)
