import os

from iatoolkit.common.interfaces.secret_provider import SecretProvider


class EnvSecretProvider(SecretProvider):
    def get_secret(self, company_short_name: str, key_name: str, default: str = None) -> str | None:
        # company_short_name is unused for env-backed resolution.
        _ = company_short_name
        return os.getenv((key_name or '').strip(), default)
