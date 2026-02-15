import abc


class SecretProvider(abc.ABC):
    @abc.abstractmethod
    def get_secret(self, company_short_name: str, key_name: str, default: str = None) -> str | None:
        """
        Returns the resolved secret value for the given company and key.
        Implementations may decide how tenant scoping is handled.
        """
        pass
