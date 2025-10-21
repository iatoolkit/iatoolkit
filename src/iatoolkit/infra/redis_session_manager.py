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
    def set(cls, key: str, value: str, **kwargs):
        """
        Método set flexible que pasa argumentos opcionales (como ex, nx)
        directamente al cliente de redis.
        """
        client = cls._get_client()
        # Pasa todos los argumentos de palabra clave adicionales al cliente real
        result = client.set(key, value, **kwargs)
        return result

    @classmethod
    def get(cls, key: str, default: str = ""):
        client = cls._get_client()
        value = client.get(key)
        result = value if value is not None else default
        return result

    @classmethod
    def hset(cls, key: str, field: str, value: str):
        """
        Establece un campo en un Hash de Redis.
        """
        client = cls._get_client()
        return client.hset(key, field, value)

    @classmethod
    def hget(cls, key: str, field: str):
        """
        Obtiene el valor de un campo de un Hash de Redis.
        Devuelve None si la clave o el campo no existen.
        """
        client = cls._get_client()
        return client.hget(key, field)

    @classmethod
    def hdel(cls, key: str, *fields):
        """
        Elimina uno o más campos de un Hash de Redis.
        """
        client = cls._get_client()
        return client.hdel(key, *fields)

    @classmethod
    def pipeline(cls):
        """
        Inicia una transacción (pipeline) de Redis.
        """
        client = cls._get_client()
        return client.pipeline()


    @classmethod
    def remove(cls, key: str):
        client = cls._get_client()
        result = client.delete(key)
        return result

    @classmethod
    def exists(cls, key: str) -> bool:
        """Verifica si una clave existe en Redis."""
        client = cls._get_client()
        # El comando EXISTS de Redis devuelve un entero (0 o 1). Lo convertimos a booleano.
        return bool(client.exists(key))

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