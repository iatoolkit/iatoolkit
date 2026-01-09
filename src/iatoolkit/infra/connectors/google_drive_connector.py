# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.infra.connectors.file_connector import FileConnector
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2.service_account import Credentials
import io
from typing import List


class GoogleDriveConnector(FileConnector):
    def __init__(self, folder_id: str, service_account_path: str = "service_account.json"):
        """
        Inicializa el conector de Google Drive utilizando la API oficial de Google.
        :param folder_id: ID de la carpeta en Google Drive.
        :param service_account_path: Ruta al archivo JSON de la cuenta de servicio.
        """
        self.folder_id = folder_id
        self.service_account_path = service_account_path
        self.drive_service = self._authenticate()

    def _authenticate(self):
        """
        Autentica en Google Drive utilizando una cuenta de servicio.
        """
        # Cargar credenciales desde el archivo de servicio
        credentials = Credentials.from_service_account_file(
            self.service_account_path,
            scopes=["https://www.googleapis.com/auth/drive"]
        )

        # Crear el cliente de Google Drive API
        service = build('drive', 'v3', credentials=credentials)
        return service

    def list_files(self) -> List[dict]:
        """
        Estándar: Lista todos los archivos como diccionarios con claves 'path', 'name' y 'metadata'.
        """
        query = f"'{self.folder_id}' in parents and trashed=false"
        results = self.drive_service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])

        return [
            {
                "path": file['id'],  # ID único del archivo en Google Drive
                "name": file['name'],  # Nombre del archivo en Google Drive
                "metadata": {}  # No hay metadatos adicionales en este caso
            }
            for file in files
        ]

    def get_file_content(self, file_path: str) -> bytes:
        """
        Obtiene el contenido de un archivo en Google Drive utilizando su ID (file_path).
        """
        request = self.drive_service.files().get_media(fileId=file_path)
        file_buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(file_buffer, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        return file_buffer.getvalue()

    def upload_file(self, file_path: str, content: bytes, content_type: str = None) -> None:
        """
        Sube un archivo a Google Drive.
        Nota: 'file_path' en este contexto se interpreta como el nombre del archivo,
        ya que GDrive usa IDs para carpetas. El archivo se subirá a la carpeta configurada (self.folder_id).
        """
        file_metadata = {
            'name': file_path, # Usamos file_path como nombre
            'parents': [self.folder_id]
        }

        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=content_type, resumable=True)

        self.drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()

    def delete_file(self, file_path: str) -> None:
        """
        Elimina un archivo de Google Drive.
        Nota: 'file_path' aquí DEBE ser el ID del archivo (fileId), no su nombre.
        """
        try:
            self.drive_service.files().delete(fileId=file_path).execute()
        except Exception:
            # Si falla (ej: no existe), podríamos loguear o ignorar según diseño.
            # Aquí asumimos propagación de error o manejo silencioso si no crítico.
            pass