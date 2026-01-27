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
import scipy.io.wavfile # Necesario para guardar el audio

# Transformers imports
from transformers import (
    CLIPProcessor, CLIPModel,
    AutoTokenizer, AutoModel,
    pipeline
)

class EndpointHandler:
    def __init__(self, path: str = ""):
        self.current_model_id = None
        self.model_instance = None
        self.processor_instance = None
        self.pipeline_instance = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logging.info(f"Handler initialized on device: {self.device}")

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
            # Lógica CLIP
            if "clip" in model_id.lower():
                self.processor_instance = CLIPProcessor.from_pretrained(model_id)
                self.model_instance = CLIPModel.from_pretrained(model_id).to(self.device)
                self.model_instance.eval()

            # Lógica Embeddings Texto
            elif "minilm" in model_id.lower():
                self.processor_instance = AutoTokenizer.from_pretrained(model_id)
                self.model_instance = AutoModel.from_pretrained(model_id).to(self.device)
                self.model_instance.eval()

            # Lógica Whisper (STT)
            elif "whisper" in model_id.lower():
                self.pipeline_instance = pipeline(
                    "automatic-speech-recognition",
                    model=model_id,
                    device=self.device
                )

            # Lógica Text-to-Speech (MMS, VibeVoice, Speech, TTS)
            # Aquí es donde fallaba antes: ahora detectamos "mms" explícitamente
            elif any(x in model_id.lower() for x in ["mms", "speech", "tts", "vibevoice"]):
                logging.info(f"Initializing TTS pipeline for {model_id}")
                self.pipeline_instance = pipeline(
                    "text-to-speech",
                    model=model_id,
                    device=self.device
                )

            self.current_model_id = model_id
            logging.info(f"Model {model_id} loaded successfully.")

        except Exception as e:
            logging.error(f"Failed to load model {model_id}: {e}")
            raise ValueError(f"Could not load model {model_id}. Error: {str(e)}")

    def _handle_clip(self, inputs: dict) -> dict:
        # (Misma lógica que tenías)
        mode = inputs.get("mode")
        if mode == "text":
            text = inputs.get("text")
            inputs_pt = self.processor_instance(text=[text], return_tensors="pt", padding=True, truncation=True).to(self.device)
            with torch.no_grad():
                emb = self.model_instance.get_text_features(**inputs_pt)
        else:
            # Simplificado para brevedad
            url = inputs.get("url") or inputs.get("presigned_url")
            if url:
                image = Image.open(requests.get(url, stream=True).raw)
                inputs_pt = self.processor_instance(images=image, return_tensors="pt").to(self.device)
                with torch.no_grad():
                    emb = self.model_instance.get_image_features(**inputs_pt)
            else:
                raise ValueError("Image URL needed")

        emb = torch.nn.functional.normalize(emb, p=2, dim=-1)
        vec = emb[0].cpu().tolist()
        return {"embedding": vec}

    def _handle_minilm(self, inputs: dict) -> dict:
        # (Misma lógica que tenías)
        text = inputs.get("text")
        encoded_input = self.processor_instance(text, padding=True, truncation=True, return_tensors='pt').to(self.device)
        with torch.no_grad():
            model_output = self.model_instance(**encoded_input)

        # Mean pooling simple
        token_embeddings = model_output[0]
        attention_mask = encoded_input['attention_mask']
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        sentence_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        sentence_embeddings = torch.nn.functional.normalize(sentence_embeddings, p=2, dim=1)
        return {"embedding": sentence_embeddings[0].cpu().tolist()}

    def _handle_tts(self, inputs: dict) -> dict:
        text = inputs.get("text")
        if not text:
            raise ValueError("Expected inputs.text for TTS.")

        # Generar audio con el pipeline
        # MMS devuelve un diccionario: {'audio': np.array, 'sampling_rate': int}
        output = self.pipeline_instance(text)

        audio_data = output["audio"]
        sampling_rate = output["sampling_rate"]

        # Escribir a buffer WAV en memoria
        wav_buffer = io.BytesIO()
        scipy.io.wavfile.write(wav_buffer, rate=sampling_rate, data=audio_data.T)

        # Codificar a Base64 para enviar por JSON
        b64_out = base64.b64encode(wav_buffer.getvalue()).decode("utf-8")

        return {
            "audio_base64": b64_out,
            "sampling_rate": sampling_rate,
            "content_type": "audio/wav"
        }

    def __call__(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Entry point principal."""
        inputs = data.get("inputs", {})
        parameters = data.get("parameters", {})

        # Recuperar ID del modelo o fallback
        requested_model_id = parameters.get("model_id", "openai/clip-vit-base-patch32")

        # 1. Cargar modelo si es necesario
        self._load_model(requested_model_id)
        model_lower = requested_model_id.lower()

        # 2. Enrutar a la función correcta
        try:
            if "clip" in model_lower:
                return self._handle_clip(inputs)
            elif "minilm" in model_lower:
                return self._handle_minilm(inputs)
            elif "whisper" in model_lower:
                # Placeholder para whisper
                return {"text": "whisper logic here"}
                # Detección robusta para TTS
            elif any(x in model_lower for x in ["mms", "speech", "tts", "vibevoice"]):
                return self._handle_tts(inputs)
            else:
                raise ValueError(f"No handler logic defined for model: {requested_model_id}")

        except Exception as e:
            logging.error(f"Inference error: {e}")
            raise ValueError(f"Inference failed: {str(e)}")