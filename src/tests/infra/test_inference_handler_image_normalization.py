import base64
import importlib
import io
import sys
import types
from unittest.mock import MagicMock

import torch
from PIL import Image


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
