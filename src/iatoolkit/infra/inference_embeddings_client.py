import numpy as np
from typing import List, Optional, Any
from huggingface_hub import InferenceClient
import logging


class InferenceEmbeddingsClient:
    """
    Cliente de embeddings personalizado usando huggingface_hub.InferenceClient.
    Compatible con la arquitectura de proveedores 'custom_class' de IAToolkit.
    """
    def __init__(
            self,
            api_key: str,
            model: str,
    ):
        """
        Args:
            api_key: El token de Hugging Face (HF_TOKEN).
            model: El ID del modelo (ej: 'BAAI/bge-m3') o la URL completa del Endpoint de Inferencia.
        """
        self.client = InferenceClient(model=model, token=api_key)

    def get_embedding(self, text: str) -> List[float]:
        """
        Genera el embedding para el texto dado usando feature_extraction.
        """
        try:
            logging.info(f"Generando embedding para '{text}'...")
            # feature_extraction es el método estándar para embeddings en InferenceClient
            embedding = self.client.feature_extraction(text)

            if isinstance(embedding, list) and len(embedding) > 0 and isinstance(embedding[0], list):
                return embedding[0]
            return embedding

        except Exception as e:
            raise RuntimeError(f"Error generando embedding con InferenceClient: {e}")

    def get_image_embedding(self, presigned_url: Optional[str] = None, image_bytes: Optional[bytes] = None) -> List[float]:
        raise NotImplementedError("Image embedding not implemented for this client.")