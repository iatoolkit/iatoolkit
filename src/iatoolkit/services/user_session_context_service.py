# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.infra.redis_session_manager import RedisSessionManager
from typing import List, Dict, Optional
import json
import logging


class UserSessionContextService:
    """
    Gestiona el contexto de la sesión del usuario usando un único Hash de Redis por sesión.
    Esto mejora la atomicidad y la eficiencia.
    """

    def _get_session_key(self, company_short_name: str, user_identifier: str, model: str = None) -> Optional[str]:
        """Devuelve la clave única de Redis para el Hash de sesión del usuario."""
        user_identifier = (user_identifier or "").strip()
        if not company_short_name or not user_identifier:
            return None

        model_key = "" if not model else f"-{model}"
        return f"session:{company_short_name}/{user_identifier}{model_key}"

    def clear_all_context(self, company_short_name: str, user_identifier: str, model: str = None):
        """Clears LLM-related context for a user (history and response IDs), preserving profile_data."""
        session_key = self._get_session_key(company_short_name, user_identifier, model=model)
        if session_key:
            # 'profile_data' should not be deleted
            RedisSessionManager.hdel(session_key, "context_version")
            RedisSessionManager.hdel(session_key, "context_history")
            RedisSessionManager.hdel(session_key, "last_response_id")

    def clear_llm_history(self, company_short_name: str, user_identifier: str, model: str = None):
        """Clears only LLM history fields (last_response_id and context_history)."""
        session_key = self._get_session_key(company_short_name, user_identifier, model=model)
        if session_key:
            RedisSessionManager.hdel(session_key, "last_response_id", "context_history")

    def get_last_response_id(self, company_short_name: str, user_identifier: str, model: str = None) -> Optional[str]:
        """Returns the last LLM response ID for this user/model combination."""
        session_key = self._get_session_key(company_short_name, user_identifier, model=model)
        if not session_key:
            return None
        return RedisSessionManager.hget(session_key, "last_response_id")

    def save_last_response_id(self,
        company_short_name: str,
        user_identifier: str,
        response_id: str,
        model: str = None,
    ):
        """Persists the last LLM response ID for this user/model combination."""
        session_key = self._get_session_key(company_short_name, user_identifier, model=model)
        if session_key:
            RedisSessionManager.hset(session_key, "last_response_id", response_id)

    def get_initial_response_id(self,
        company_short_name: str,
        user_identifier: str,
        model: str = None,
    ) -> Optional[str]:
        """
        Returns the initial LLM response ID for this user/model combination.
        This ID represents the state right after the context was set on the LLM.
        """
        session_key = self._get_session_key(company_short_name, user_identifier, model=model)
        if not session_key:
            return None
        return RedisSessionManager.hget(session_key, "initial_response_id")

    def save_initial_response_id(self,
            company_short_name: str,
            user_identifier: str,
            response_id: str,
            model: str = None,
    ):
        """Persists the initial LLM response ID for this user/model combination."""
        session_key = self._get_session_key(company_short_name, user_identifier, model=model)
        if session_key:
            RedisSessionManager.hset(session_key, "initial_response_id", response_id)

    def save_context_history(
            self,
            company_short_name: str,
            user_identifier: str,
            context_history: List[Dict],
            model: str = None,
    ):
        """Serializes and stores the context history for this user/model combination."""
        session_key = self._get_session_key(company_short_name, user_identifier, model=model)
        if session_key:
            try:
                history_json = json.dumps(context_history)
                RedisSessionManager.hset(session_key, "context_history", history_json)
            except (TypeError, ValueError) as e:
                logging.error(f"Error serializing context_history for {session_key}: {e}")

    def get_context_history(
            self,
            company_short_name: str,
            user_identifier: str,
            model: str = None,
    ) -> Optional[List[Dict]]:
        """Reads and deserializes the context history for this user/model combination."""
        session_key = self._get_session_key(company_short_name, user_identifier, model=model)
        if not session_key:
            return None

        history_json = RedisSessionManager.hget(session_key, "context_history")
        if not history_json:
            return []

        try:
            return json.loads(history_json)
        except json.JSONDecodeError:
            return []

    def save_profile_data(self, company_short_name: str, user_identifier: str, data: dict):
        session_key = self._get_session_key(company_short_name, user_identifier)
        if session_key:
            try:
                data_json = json.dumps(data)
                RedisSessionManager.hset(session_key, 'profile_data', data_json)
            except (TypeError, ValueError) as e:
                logging.error(f"Error al serializar profile_data para {session_key}: {e}")

    def get_profile_data(self, company_short_name: str, user_identifier: str) -> dict:
        session_key = self._get_session_key(company_short_name, user_identifier)
        if not session_key:
            return {}

        data_json = RedisSessionManager.hget(session_key, 'profile_data')
        if not data_json:
            return {}

        try:
            return json.loads(data_json)
        except json.JSONDecodeError:
            return {}

    def save_context_version(self,
            company_short_name: str,
            user_identifier: str,
            version: str,
            model: str = None,
        ):
        """Saves the context version for this user/model combination."""
        session_key = self._get_session_key(company_short_name, user_identifier, model=model)
        if session_key:
            RedisSessionManager.hset(session_key, "context_version", version)

    def get_context_version(self,
            company_short_name: str,
            user_identifier: str,
            model: str = None,
            ) -> Optional[str]:
        """Returns the context version for this user/model combination."""
        session_key = self._get_session_key(company_short_name, user_identifier, model=model)
        if not session_key:
            return None
        return RedisSessionManager.hget(session_key, "context_version")

    def save_prepared_context(self,
            company_short_name: str,
            user_identifier: str,
            context: str,
            version: str,
            model: str = None,
            ):
        """Stores a pre-rendered system context and its version, ready to be sent to the LLM."""
        session_key = self._get_session_key(company_short_name, user_identifier, model=model)
        if session_key:
            RedisSessionManager.hset(session_key, "prepared_context", context)
            RedisSessionManager.hset(session_key, "prepared_context_version", version)

    def get_and_clear_prepared_context(self,
            company_short_name: str,
            user_identifier: str,
            model: str = None,
            ) -> tuple:
        """
        Atomically retrieves the prepared context and its version and then deletes them
        to guarantee they are consumed only once.
        """
        session_key = self._get_session_key(company_short_name, user_identifier, model=model)
        if not session_key:
            return None, None

        pipe = RedisSessionManager.pipeline()
        pipe.hget(session_key, "prepared_context")
        pipe.hget(session_key, "prepared_context_version")
        pipe.hdel(session_key, "prepared_context", "prepared_context_version")
        results = pipe.execute()

        # results[0] is the context, results[1] is the version
        return (results[0], results[1]) if results else (None, None)

    # --- Métodos de Bloqueo ---
    def acquire_lock(self, lock_key: str, expire_seconds: int) -> bool:
        """Intenta adquirir un lock. Devuelve True si se adquiere, False si no."""
        # SET con NX (solo si no existe) y EX (expiración) es una operación atómica.
        return RedisSessionManager.set(lock_key, "1", ex=expire_seconds, nx=True)

    def release_lock(self, lock_key: str):
        """Libera un lock."""
        RedisSessionManager.remove(lock_key)

    def is_locked(self, lock_key: str) -> bool:
        """Verifica si un lock existe."""
        return RedisSessionManager.exists(lock_key)