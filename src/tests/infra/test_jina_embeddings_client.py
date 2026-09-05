import base64

import pytest

from iatoolkit.infra.jina_embeddings_client import JinaEmbeddingsClient


class FakeCallService:
    def __init__(self, response, status=200):
        self.response = response
        self.status = status
        self.calls = []

    def post(self, endpoint, json_dict, headers, timeout):
        self.calls.append({
            "endpoint": endpoint,
            "json_dict": json_dict,
            "headers": headers,
            "timeout": timeout,
        })
        return self.response, self.status


def test_get_embedding_posts_text_payload_and_returns_vector():
    call_service = FakeCallService({"data": [{"embedding": [0.1, 0.2]}]})
    client = JinaEmbeddingsClient(api_key="key", call_service=call_service, model="jina-test", normalized=False)

    assert client.get_embedding("hello") == [0.1, 0.2]
    call = call_service.calls[0]
    assert call["endpoint"] == "https://api.jina.ai/v1/embeddings"
    assert call["headers"] == {
        "Authorization": "Bearer key",
        "Content-Type": "application/json",
    }
    assert call["timeout"] == (10, 120.0)
    assert call["json_dict"] == {
        "model": "jina-test",
        "normalized": False,
        "embedding_type": "float",
        "input": ["hello"],
    }


def test_get_embeddings_orders_vectors_by_api_index():
    call_service = FakeCallService({
        "data": [
            {"index": 1, "embedding": [2.0]},
            {"index": 0, "embedding": [1.0]},
        ]
    })
    client = JinaEmbeddingsClient(api_key="key", call_service=call_service)

    assert client.get_embeddings(["first", "second"]) == [[1.0], [2.0]]


def test_get_embeddings_rejects_mismatched_response_count():
    call_service = FakeCallService({"data": [{"index": 0, "embedding": [1.0]}]})
    client = JinaEmbeddingsClient(api_key="key", call_service=call_service)

    with pytest.raises(ValueError, match="Jina returned 1 embeddings for 2 inputs"):
        client.get_embeddings(["first", "second"])


def test_get_image_embedding_supports_presigned_url():
    call_service = FakeCallService({"data": [{"embedding": [0.3, 0.4]}]})
    client = JinaEmbeddingsClient(api_key="key", call_service=call_service)

    assert client.get_image_embedding(presigned_url="https://example.com/image.jpg") == [0.3, 0.4]
    assert call_service.calls[0]["json_dict"]["input"] == [{"image": "https://example.com/image.jpg"}]


def test_get_image_embedding_supports_bytes_as_data_url():
    call_service = FakeCallService({"data": [{"embedding": [0.5, 0.6]}]})
    client = JinaEmbeddingsClient(api_key="key", call_service=call_service)

    assert client.get_image_embedding(image_bytes=b"image-bytes") == [0.5, 0.6]
    image_payload = call_service.calls[0]["json_dict"]["input"][0]["image"]
    assert image_payload == f"data:image/jpeg;base64,{base64.b64encode(b'image-bytes').decode('utf-8')}"


def test_get_image_embedding_requires_image_input():
    client = JinaEmbeddingsClient(api_key="key", call_service=FakeCallService({}))

    with pytest.raises(ValueError, match="Missing image data"):
        client.get_image_embedding()


def test_post_raises_on_non_success_status():
    client = JinaEmbeddingsClient(api_key="key", call_service=FakeCallService({"error": "bad"}, status=500))

    with pytest.raises(ValueError, match="Jina API Error 500"):
        client.get_embedding("hello")
