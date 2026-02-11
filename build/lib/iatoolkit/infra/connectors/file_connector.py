# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from abc import ABC, abstractmethod
from typing import List, Optional


class FileConnector(ABC):
    @abstractmethod
    def list_files(self) -> List[str]:
        pass

    @abstractmethod
    def get_file_content(self, file_path: str) -> bytes:
        pass

    @abstractmethod
    def delete_file(self, file_path: str) -> None:
        pass

    @abstractmethod
    def upload_file(self, file_path: str, content: bytes, content_type: str = None) -> None:
        pass

    def generate_presigned_url(self, file_path: str, expiration: int = 3600) -> Optional[str]:
        return None