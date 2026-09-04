# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import os
from iatoolkit.infra.connectors.file_connector import FileConnector
from typing import List
from iatoolkit.common.exceptions import IAToolkitException


class LocalFileConnector(FileConnector):
    def __init__(self, directory: str):
        local_root = os.getenv("ROOT_DIR_LOCAL_FILES", '')
        self.directory = os.path.join(local_root, directory)

    def list_files(self, prefix: str | None = None) -> List[dict]:
        """
        Estándar: Lista todos los archivos como diccionarios con claves 'path', 'name' y 'metadata'.
        """
        try:
            files = [
                os.path.join(self.directory, f)
                for f in os.listdir(self.directory)
                if os.path.isfile(os.path.join(self.directory, f))
            ]

            return [
                {
                    "path": file,  # Ruta completa al archivo local
                    "name": os.path.basename(file),  # Nombre del archivo
                    "metadata": {"size": os.path.getsize(file), "last_modified": os.path.getmtime(file)}
                }
                for file in files
            ]
        except Exception as e:
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                               f"Error procesando el directorio {self.directory}: {e}")

    def _resolve_within_root(self, file_path: str) -> str:
        """
        Maps a storage key / path onto the filesystem and refuses anything that
        escapes the connector's root directory. `file_path` may be relative (a
        storage key) or absolute (the `path` values list_files() hands back);
        either way the real, symlink-resolved target must stay under root -
        otherwise a caller-controlled key like `../../etc/passwd` or
        `/proc/self/environ` turns this connector into an arbitrary file
        read/write/delete on the host.
        """
        candidate = str(file_path or "").strip()
        if not candidate or "\x00" in candidate:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER,
                                     "Invalid storage path.")

        root = os.path.realpath(self.directory)
        target = candidate if os.path.isabs(candidate) else os.path.join(root, candidate)
        resolved = os.path.realpath(target)
        if resolved != root and not resolved.startswith(root + os.sep):
            raise IAToolkitException(IAToolkitException.ErrorType.PERMISSION,
                                     f"Storage path escapes the configured root directory: {file_path}")
        return resolved

    def get_file_content(self, file_path: str) -> bytes:
        full_path = self._resolve_within_root(file_path)
        try:
            with open(full_path, 'rb') as f:
                return f.read()
        except Exception as e:
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                               f"Error leyendo el archivo {file_path}: {e}")

    def upload_file(self, file_path: str, content: bytes, content_type: str = None) -> None:
        # Nota: file_path debe ser relativo al directorio raíz configurado
        full_path = self._resolve_within_root(file_path)

        # Asegurar que el directorio destino existe
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'wb') as f:
                f.write(content)
        except Exception as e:
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                                     f"Error escribiendo el archivo {file_path}: {e}")

    def delete_file(self, file_path: str) -> None:
        full_path = self._resolve_within_root(file_path)
        try:
            if os.path.exists(full_path):
                os.remove(full_path)
        except Exception as e:
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                                     f"Error eliminando el archivo {file_path}: {e}")

    def generate_presigned_url(self, file_path: str, expiration: int = 3600) -> str:
        raise NotImplementedError("not implemented yet")
