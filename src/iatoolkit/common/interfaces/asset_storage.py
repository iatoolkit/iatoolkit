from enum import Enum
from typing import List
import abc


class AssetType(Enum):
    CONFIG = "config"
    PROMPT = "prompts"
    SCHEMA = "schema"
    CONTEXT = "context"


class AssetRepository(abc.ABC):
    @abc.abstractmethod
    def exists(self, company_short_name: str, asset_type: AssetType, filename: str) -> bool:
        pass

    @abc.abstractmethod
    def read_text(self, company_short_name: str, asset_type: AssetType, filename: str) -> str:
        pass

    @abc.abstractmethod
    def list_files(self, company_short_name: str, asset_type: AssetType, extension: str = None) -> List[str]:
        pass

    @abc.abstractmethod
    def write_text(self, company_short_name: str, asset_type: AssetType, filename: str, content: str) -> None:
        """Creates or updates a text asset."""
        pass

    @abc.abstractmethod
    def delete(self, company_short_name: str, asset_type: AssetType, filename: str) -> None:
        """Deletes an asset if it exists."""
        pass