# src/iatoolkit/integrations/jina_embeddings_client.py
# Simple Jina embeddings client (text + image bytes)
import base64
from typing import List, Union
from iatoolkit.infra.call_service import CallServiceClient


class JinaEmbeddingsClient:
    """
    Expected by CustomClassClientWrapper:
      - get_embedding(text) -> List[float]
      - get_image_embedding(image_bytes) -> List[float]
    """

    def __init__(
        self,
        api_key: str,
        call_service: CallServiceClient,
        model: str = "jina-embeddings-v4",
        endpoint: str = "https://api.jina.ai/v1/embeddings",
        normalized: bool = True,
    ):
        self.api_key = api_key
        self.call_service = call_service
        self.model = model
        self.endpoint = endpoint
        self.normalized = normalized

    def get_embedding(self, text: str) -> List[float]:
        payload = {
            "model": self.model,
            "normalized": self.normalized,
            "embedding_type": "float",
            "input": [text],
        }
        response = self._post(payload)
        return response["data"][0]["embedding"]

    def get_image_embedding(self, image_input: Union[bytes, str]) -> list[float]:
        if isinstance(image_input, str):
            # URL path
            payload = {
                "model": self.model,
                "embedding_type": "float",
                "normalized": self.normalized,
                "input": [{"image": image_input}],
            }
            response = self._post(payload)
            return response["data"][0]["embedding"]

        # bytes path -> Data URL
        b64 = base64.b64encode(image_input).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"  # or detect mime
        payload = {
            "model": self.model,
            "embedding_type": "float",
            "normalized": self.normalized,
            "input": [{"image": data_url}],
        }
        response = self._post(payload)
        return response["data"][0]["embedding"]

    def _post(self, payload: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        resp, status = self.call_service.post(
                    self.endpoint,
                    json_dict=payload,
                    headers=headers,
                    timeout=(10, 120.0)
        )
        if status != 200:
            raise ValueError(f"Jina API Error {status}: {resp}")
        return resp