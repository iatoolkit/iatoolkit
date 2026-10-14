# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Iterator, List

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from iatoolkit.infra.connectors.file_connector import FileConnector

SCOPE_FULL = "https://www.googleapis.com/auth/drive"
SCOPE_READ_ONLY = "https://www.googleapis.com/auth/drive.readonly"

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
SHORTCUT_MIME_TYPE = "application/vnd.google-apps.shortcut"
GOOGLE_APPS_PREFIX = "application/vnd.google-apps."

# Google's own formats have no bytes to download: they are exported. Each one
# goes to a format the document parsers already read.
EXPORT_FORMATS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
}

FILE_FIELDS = "id, name, mimeType, parents, md5Checksum, modifiedTime, size, trashed, headRevisionId"


@dataclass(frozen=True)
class DriveFile:
    """A file as Drive describes it, with its path below the folder it was found from."""
    id: str
    name: str
    mime_type: str
    path: str = ""
    parents: tuple[str, ...] = ()
    md5_checksum: str | None = None
    modified_time: str | None = None
    size: int | None = None
    trashed: bool = False

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME_TYPE

    @property
    def is_shortcut(self) -> bool:
        return self.mime_type == SHORTCUT_MIME_TYPE

    @property
    def is_google_native(self) -> bool:
        return self.mime_type.startswith(GOOGLE_APPS_PREFIX)

    @property
    def exportable(self) -> bool:
        return self.mime_type in EXPORT_FORMATS

    @property
    def fingerprint(self) -> str:
        """What tells one version of the file from the next: the content hash for
        uploaded files, the modification time for Google's own formats (they have
        no md5)."""
        return str(self.md5_checksum or self.modified_time or "")

    @classmethod
    def from_api(cls, payload: dict, *, path: str = "") -> "DriveFile":
        size = payload.get("size")
        return cls(
            id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            mime_type=str(payload.get("mimeType") or ""),
            path=path,
            parents=tuple(payload.get("parents") or ()),
            md5_checksum=payload.get("md5Checksum"),
            modified_time=payload.get("modifiedTime"),
            size=int(size) if str(size or "").isdigit() else None,
            trashed=bool(payload.get("trashed")),
        )


@dataclass(frozen=True)
class DriveChange:
    file_id: str
    removed: bool
    file: DriveFile | None = None


@dataclass(frozen=True)
class DriveChangesPage:
    changes: list[DriveChange] = field(default_factory=list)
    next_page_token: str | None = None
    new_start_page_token: str | None = None


class GoogleDriveConnector(FileConnector):
    PAGE_SIZE = 1000

    def __init__(
        self,
        folder_id: str,
        service_account_path: str = "service_account.json",
        service_account_info: dict | None = None,
        read_only: bool = False,
    ):
        """
        Google Drive through a service account.

        :param folder_id: the folder `list_files` lists and `upload_file` writes to.
        :param read_only: ask only for `drive.readonly` (whoever only reads, such
            as Memoria's sync, should); the default keeps the full scope that
            uploads and deletes need.
        """
        self.folder_id = folder_id
        self.service_account_path = service_account_path
        self.service_account_info = service_account_info
        self.scopes = [SCOPE_READ_ONLY if read_only else SCOPE_FULL]
        self.drive_service = self._authenticate()

    def _authenticate(self):
        if self.service_account_info:
            credentials = Credentials.from_service_account_info(self.service_account_info, scopes=self.scopes)
        else:
            credentials = Credentials.from_service_account_file(self.service_account_path, scopes=self.scopes)
        return build('drive', 'v3', credentials=credentials, cache_discovery=False)

    @property
    def service_account_email(self) -> str | None:
        info = self.service_account_info or {}
        return str(info.get("client_email") or "").strip() or None

    # --- FileConnector ------------------------------------------------------

    def list_files(self, prefix: str | None = None) -> List[dict]:
        """
        Every direct child of the configured folder, as dicts with 'path' (the
        file id), 'name' and 'metadata'. Follows every page of results: a folder
        with more than one page used to be cut silently at the first.
        """
        return [
            {
                "path": item.id,
                "name": item.name,
                "metadata": {
                    "mime_type": item.mime_type,
                    "md5_checksum": item.md5_checksum,
                    "modified_time": item.modified_time,
                    "size": item.size,
                },
            }
            for item in self.list_children(self.folder_id)
        ]

    def get_file_content(self, file_path: str) -> bytes:
        """Bytes of a file by id (exported first if it is a Google Docs/Sheets/Slides file)."""
        content, _, _ = self.download(file_path)
        return content

    def upload_file(self, file_path: str, content: bytes, content_type: str = None) -> None:
        """
        Uploads to the configured folder. Drive addresses folders by id, so
        `file_path` is used as the file name.
        """
        file_metadata = {'name': file_path, 'parents': [self.folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=content_type, resumable=True)
        self.drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()

    def delete_file(self, file_path: str) -> None:
        """Deletes by file id; a file that is already gone is not an error."""
        try:
            self.drive_service.files().delete(fileId=file_path).execute()
        except Exception:
            pass

    def generate_presigned_url(self, file_path: str, expiration: int = 3600) -> str:
        raise NotImplementedError("not implemented yet")

    # --- Reading a folder tree ---------------------------------------------

    def get_file(self, file_id: str) -> DriveFile | None:
        """The file or folder, or None when it does not exist or is not shared with this account."""
        try:
            payload = self.drive_service.files().get(
                fileId=file_id,
                fields=FILE_FIELDS,
                supportsAllDrives=True,
            ).execute()
        except HttpError as exc:
            if getattr(exc, "status_code", None) in (403, 404) or getattr(getattr(exc, "resp", None), "status", None) in (403, 404):
                return None
            raise
        return DriveFile.from_api(payload)

    def list_children(self, folder_id: str) -> Iterator[DriveFile]:
        """Direct children of a folder (files, folders and shortcuts), every page."""
        page_token = None
        while True:
            response = self.drive_service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields=f"nextPageToken, files({FILE_FIELDS})",
                pageSize=self.PAGE_SIZE,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            for payload in response.get("files", []):
                yield DriveFile.from_api(payload)
            page_token = response.get("nextPageToken")
            if not page_token:
                return

    def walk(self, folder_id: str | None = None) -> Iterator[DriveFile]:
        """
        Every file below a folder, with its path relative to it ("Contratos/2026").

        Folders are entered, never returned. Shortcuts are skipped: following one
        would bring in a file from outside the folder that was shared.
        """
        root = folder_id or self.folder_id
        pending = [(root, "")]
        seen = {root}
        while pending:
            current, path = pending.pop(0)
            for item in self.list_children(current):
                if item.is_folder:
                    if item.id not in seen:
                        seen.add(item.id)
                        pending.append((item.id, f"{path}/{item.name}".strip("/")))
                    continue
                if item.is_shortcut:
                    continue
                yield DriveFile(
                    id=item.id, name=item.name, mime_type=item.mime_type, path=path,
                    parents=item.parents, md5_checksum=item.md5_checksum,
                    modified_time=item.modified_time, size=item.size, trashed=item.trashed,
                )

    def download(self, file_id: str, mime_type: str | None = None) -> tuple[bytes, str | None, str | None]:
        """
        The file's bytes, the extension to give it and their MIME type. Google
        Docs, Sheets and Slides are exported (docx, xlsx, pdf); other Google
        formats (forms, maps) cannot be read and raise ValueError.
        """
        if mime_type is None:
            meta = self.get_file(file_id)
            mime_type = meta.mime_type if meta else ""
        if str(mime_type).startswith(GOOGLE_APPS_PREFIX):
            export = EXPORT_FORMATS.get(mime_type)
            if not export:
                raise ValueError(f"Google format '{mime_type}' cannot be exported")
            export_mime, extension = export
            request = self.drive_service.files().export_media(fileId=file_id, mimeType=export_mime)
            return self._read(request), extension, export_mime
        request = self.drive_service.files().get_media(fileId=file_id, supportsAllDrives=True)
        return self._read(request), None, mime_type or None

    @staticmethod
    def _read(request) -> bytes:
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    # --- Changes ------------------------------------------------------------

    def get_start_page_token(self) -> str:
        """Where to start reading changes from: everything after now."""
        response = self.drive_service.changes().getStartPageToken(supportsAllDrives=True).execute()
        return str(response.get("startPageToken") or "")

    def list_changes(self, page_token: str) -> DriveChangesPage:
        """
        One page of what changed since `page_token`, for everything this account
        can see. When `new_start_page_token` is set the caller is up to date and
        stores it; otherwise it keeps reading with `next_page_token`.
        """
        response = self.drive_service.changes().list(
            pageToken=page_token,
            pageSize=self.PAGE_SIZE,
            fields=f"nextPageToken, newStartPageToken, changes(fileId, removed, file({FILE_FIELDS}))",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            spaces="drive",
        ).execute()
        changes = [
            DriveChange(
                file_id=str(change.get("fileId") or ""),
                removed=bool(change.get("removed")),
                file=DriveFile.from_api(change["file"]) if isinstance(change.get("file"), dict) else None,
            )
            for change in response.get("changes", [])
        ]
        return DriveChangesPage(
            changes=changes,
            next_page_token=response.get("nextPageToken"),
            new_start_page_token=response.get("newStartPageToken"),
        )
