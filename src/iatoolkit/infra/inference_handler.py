from typing import Any, Dict, List
import base64
import io
import logging
import gc
import json

import requests
import torch
import numpy as np
from PIL import Image
import scipy.io.wavfile
import tempfile
from diffusers import DiffusionPipeline, DPMSolverMultistepScheduler
from diffusers.utils import export_to_video

# Transformers imports
from transformers import (
    CLIPProcessor, CLIPModel,
    AutoTokenizer, AutoModel,
    pipeline
)

class EndpointHandler:
    TEXT_EMBEDDING_MODEL_HINTS = (
        "minilm",
        "bge",
        "e5",
        "gte",
        "mpnet",
        "instructor",
        "nomic-embed",
        "jina-embeddings",
        "snowflake-arctic-embed",
        "stella",
    )

    def __init__(self, path: str = ""):
        self.current_model_id = None
        self.model_instance = None
        self.processor_instance = None
        self.pipeline_instance = None

        # 1. Detección Inteligente de Hardware
        if torch.cuda.is_available():
            self.device = "cuda"
            self.dtype = torch.float16 # GPU = Rápido
            logging.info("Handler initialized on CUDA (GPU) with float16")
        else:
            self.device = "cpu"
            self.dtype = torch.float32 # CPU = Compatible
            logging.info("Handler initialized on CPU with float32")

    @classmethod
    def _is_text_embedding_model(cls, model_id: str) -> bool:
        if not isinstance(model_id, str):
            return False
        model_lower = model_id.lower()
        if "clip" in model_lower:
            return False
        return any(hint in model_lower for hint in cls.TEXT_EMBEDDING_MODEL_HINTS)

    def _clean_memory(self):
        if self.model_instance is not None:
            del self.model_instance
        if self.processor_instance is not None:
            del self.processor_instance
        if self.pipeline_instance is not None:
            del self.pipeline_instance

        self.model_instance = None
        self.processor_instance = None
        self.pipeline_instance = None

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _load_model(self, model_id: str):
        if self.current_model_id == model_id:
            return

        logging.info(f"Loading new model: {model_id}...")
        self._clean_memory()

        try:
            # CLIP, text embeddings, Whisper...
            if "clip" in model_id.lower():
                self.processor_instance = CLIPProcessor.from_pretrained(model_id)
                self.model_instance = CLIPModel.from_pretrained(model_id).to(self.device)
                self.model_instance.eval()

            elif self._is_text_embedding_model(model_id):
                self.processor_instance = AutoTokenizer.from_pretrained(model_id)
                self.model_instance = AutoModel.from_pretrained(model_id).to(self.device)
                self.model_instance.eval()

            elif "whisper" in model_id.lower():
                self.pipeline_instance = pipeline(
                    "automatic-speech-recognition",
                    model=model_id,
                    device=self.device
                )

            # --- GENERACIÓN DE IMAGEN (SD / TinySD) ---
            elif any(x in model_id.lower() for x in ["stable-diffusion", "tiny-sd", "sd"]):
                logging.info(f"Initializing Diffusion Pipeline for {model_id}")

                # INTENTO 1: Carga estándar (busca safetensors por defecto en versiones nuevas)
                try:
                    self.pipeline_instance = DiffusionPipeline.from_pretrained(
                        model_id,
                        torch_dtype=self.dtype,
                        use_safetensors=True
                    )
                except Exception as e:
                    logging.warning(f"Safetensors load failed ({e}), trying .bin weights...")
                    # INTENTO 2: Fallback a .bin (necesario para tiny-sd)
                    self.pipeline_instance = DiffusionPipeline.from_pretrained(
                        model_id,
                        torch_dtype=self.dtype,
                        use_safetensors=False
                    )

                self.pipeline_instance.to(self.device)

                # Optimizaciones
                if self.device == "cuda":
                    self.pipeline_instance.enable_attention_slicing()

            # --- TEXT TO SPEECH ---
            elif any(x in model_id.lower() for x in ["mms", "speech", "tts", "vibevoice"]):
                logging.info(f"Initializing TTS pipeline for {model_id}")
                self.pipeline_instance = pipeline(
                    "text-to-speech",
                    model=model_id,
                    device=self.device
                )

            # --- VIDEO ---
            elif "text-to-video" in model_id.lower():
                logging.info(f"Initializing Video Pipeline for {model_id}")
                self.pipeline_instance = DiffusionPipeline.from_pretrained(
                    model_id,
                    torch_dtype=self.dtype,
                    variant="fp16" if self.device == "cuda" else None
                ).to(self.device)

                self.pipeline_instance.scheduler = DPMSolverMultistepScheduler.from_config(
                    self.pipeline_instance.scheduler.config
                )

                if self.device == "cuda":
                    self.pipeline_instance.enable_model_cpu_offload()

            else:
                raise ValueError(f"No handler logic defined for model: {model_id}")

            self.current_model_id = model_id
            logging.info(f"Model {model_id} loaded successfully.")

        except Exception as e:
            logging.error(f"Failed to load model {model_id}: {e}")
            raise ValueError(f"Could not load model {model_id}. Error: {str(e)}")

    def _handle_clip(self, inputs: dict) -> dict:
        mode = inputs.get("mode")
        if mode == "text":
            text = inputs.get("text")
            inputs_pt = self.processor_instance(text=[text], return_tensors="pt", padding=True, truncation=True).to(self.device)
            with torch.no_grad():
                emb = self.model_instance.get_text_features(**inputs_pt)
        else:
            url = inputs.get("url") or inputs.get("presigned_url")
            base64_image = inputs.get("base64")

            if url:
                image = Image.open(requests.get(url, stream=True).raw)
            elif base64_image:
                image = Image.open(io.BytesIO(base64.b64decode(base64_image)))
            else:
                raise ValueError("Image URL or base64 needed")

            inputs_pt = self.processor_instance(images=image, return_tensors="pt").to(self.device)
            with torch.no_grad():
                emb = self.model_instance.get_image_features(**inputs_pt)
        emb = torch.nn.functional.normalize(emb, p=2, dim=-1)
        vec = emb[0].cpu().tolist()
        return {"embedding": vec}

    def _handle_text_embedding(self, inputs: dict) -> dict:
        text = inputs.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Expected inputs.text for text embedding generation.")

        encoded_input = self.processor_instance(
            text,
            padding=True,
            truncation=True,
            return_tensors='pt'
        ).to(self.device)
        with torch.no_grad():
            model_output = self.model_instance(**encoded_input)

        token_embeddings = model_output[0]
        attention_mask = encoded_input['attention_mask']
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        sentence_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(
            input_mask_expanded.sum(1),
            min=1e-9
        )
        sentence_embeddings = torch.nn.functional.normalize(sentence_embeddings, p=2, dim=1)
        return {"embedding": sentence_embeddings[0].cpu().tolist()}

    # Backward-compatible alias: existing tests/callers may still refer to _handle_minilm
    def _handle_minilm(self, inputs: dict) -> dict:
        return self._handle_text_embedding(inputs)

    def _handle_tts(self, inputs: dict) -> dict:
        text = inputs.get("text")
        output = self.pipeline_instance(text)
        audio_data = output["audio"]
        sampling_rate = output["sampling_rate"]
        wav_buffer = io.BytesIO()
        scipy.io.wavfile.write(wav_buffer, rate=sampling_rate, data=audio_data.T)
        b64_out = base64.b64encode(wav_buffer.getvalue()).decode("utf-8")
        return {"audio_base64": b64_out, "sampling_rate": sampling_rate, "content_type": "audio/wav"}

    def _handle_text_to_video(self, inputs: dict) -> dict:
        prompt = inputs.get("text")
        video_frames = self.pipeline_instance(prompt, num_inference_steps=25).frames
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
            export_to_video(video_frames[0], tmp_file.name, fps=10)
            with open(tmp_file.name, "rb") as f:
                b64_out = base64.b64encode(f.read()).decode("utf-8")
        return {"video_base64": b64_out, "content_type": "video/mp4"}

    def _handle_text_to_image(self, inputs: dict) -> dict:
        prompt = inputs.get("text")
        if not prompt:
            raise ValueError("Expected inputs.text for image generation.")

        image = self.pipeline_instance(prompt=prompt, num_inference_steps=25).images[0]

        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")

        return {"image_base64": img_str, "content_type": "image/png"}

    def __call__(self, data: Dict[str, Any]) -> Dict[str, Any]:
        inputs = data.get("inputs", {})
        parameters = data.get("parameters", {})
        requested_model_id = parameters.get("model_id", "openai/clip-vit-base-patch32")

        self._load_model(requested_model_id)
        model_lower = requested_model_id.lower()

        try:
            if "clip" in model_lower:
                return self._handle_clip(inputs)
            elif self._is_text_embedding_model(requested_model_id):
                return self._handle_text_embedding(inputs)
            elif any(x in model_lower for x in ["stable-diffusion", "tiny-sd", "sd"]):
                return self._handle_text_to_image(inputs)
            elif any(x in model_lower for x in ["mms", "speech", "tts", "vibevoice"]):
                return self._handle_tts(inputs)
            elif "text-to-video" in model_lower:
                return self._handle_text_to_video(inputs)
            elif "whisper" in model_lower:
                return {"text": "whisper logic here"}
            else:
                raise ValueError(f"No handler logic defined for model: {requested_model_id}")

        except Exception as e:
            logging.error(f"Inference error: {e}")
            raise ValueError(f"Inference failed: {str(e)}")