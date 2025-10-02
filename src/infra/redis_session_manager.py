# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
import os
import redis
import json
from urllib.parse import urlparse


class RedisSessionManager:
    """
    SessionManager que usa Redis directamente para datos persistentes como llm_history.
    Separado de Flask session para tener control total sobre el ciclo de vida de los datos.
    """
    _client = None

    @classmethod
    def _get_client(cls):
        if cls._client is None:
            # Usar exactamente los mismos parámetros que Flask-Session
            url = urlparse(os.environ.get("REDIS_URL"))
            cls._client = redis.Redis(
                host=url.hostname,
                port=url.port,
                password=url.password,
                ssl=(url.scheme == "rediss"),
                ssl_cert_reqs=None,
                decode_responses=True  # Importante para strings
            )
            # verify connection
            cls._client.ping()
            info = cls._client.info(section="server")
            db = cls._client.connection_pool.connection_kwargs.get('db', 0)
        return cls._client

    @classmethod
    def set(cls, key: str, value: str, ex: int = None):
        client = cls._get_client()
        result = client.set(key, value, ex=ex)
        return result

    @classmethod
    def get(cls, key: str, default: str = ""):
        client = cls._get_client()
        value = client.get(key)
        result = value if value is not None else default
        return result

    @classmethod
    def remove(cls, key: str):
        client = cls._get_client()
        result = client.delete(key)
        return result

    @classmethod
    def set_json(cls, key: str, value: dict, ex: int = None):
        json_str = json.dumps(value)
        return cls.set(key, json_str, ex=ex)

    @classmethod
    def get_json(cls, key: str, default: dict = None):
        if default is None:
            default = {}

        json_str = cls.get(key, "")
        if not json_str:
            return default

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            logging.warning(f"[RedisSessionManager] Invalid JSON in key '{key}': {json_str}")
            return default