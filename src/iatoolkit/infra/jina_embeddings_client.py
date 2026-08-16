# src/iatoolkit/integrations/jina_embeddings_client.py
# Simple Jina embeddings client (text + image bytes)
import base64
from typing import List, Union, Optional
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

    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch in one request. The API already took a list; this uses it."""
        payload = {
            "model": self.model,
            "normalized": self.normalized,
            "embedding_type": "float",
            "input": list(texts),
        }
        response = self._post(payload)
        data = response["data"]
        if len(data) != len(texts):
            raise ValueError(f"Jina returned {len(data)} embeddings for {len(texts)} inputs.")
        # Sort by the API's own index rather than trusting arrival order: a silent
        # reordering would attach each vector to the wrong text.
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in ordered]

    def get_image_embedding(self,
                            presigned_url: Optional[str] = None,
                            image_bytes: Optional[bytes] = None
                            ) -> list[float]:
        if presigned_url:
            # URL path
            payload = {
                "model": self.model,
                "embedding_type": "float",
                "normalized": self.normalized,
                "input": [{"image": presigned_url}],
            }
            response = self._post(payload)
            return response["data"][0]["embedding"]

        # bytes path -> Data URL
        if image_bytes:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            data_url = f"data:image/jpeg;base64,{b64}"  # or detect mime
            payload = {
                "model": self.model,
                "embedding_type": "float",
                "normalized": self.normalized,
                "input": [{"image": data_url}],
            }
            response = self._post(payload)
            return response["data"][0]["embedding"]

        raise ValueError("Missing image data (presigned_url or image_bytes).")

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