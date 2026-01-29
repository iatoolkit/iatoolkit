# iatoolkit/services/embedding_service.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
from sqlalchemy.testing.plugin.plugin_base import file_config

from iatoolkit.repositories.models import Document, VSImage, DocumentStatus
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.vs_repo import VSRepo
from iatoolkit.services.embedding_service import EmbeddingService
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.exceptions import IAToolkitException
from injector import inject
import logging
import hashlib
import mimetypes


class VisualKnowledgeBaseService:
    @inject
    def __init__(self,
                 document_repo: DocumentRepo,
                 vs_repo: VSRepo,
                 profile_repo: ProfileRepo,
                 embedding_service: EmbeddingService,
                 storage_service: StorageService,
                 i18n_service: I18nService):
        self.document_repo = document_repo
        self.vs_repo = vs_repo
        self.profile_repo = profile_repo
        self.embedding_service = embedding_service
        self.storage_service = storage_service
        self.i18n_service = i18n_service

    def ingest_image_sync(self,
                          company,
                          filename: str,
                          content: bytes,
                          user_identifier: str = None,
                          metadata: dict = None,
                          collection_type_id: int = None) -> Document:
        """
        Processes an image: Upload -> Embed -> Save (Document + VSImage).
        """
        # 1. Deduplication Check
        file_hash = hashlib.sha256(content).hexdigest()
        existing_doc = self.document_repo.get_by_hash(company.id, file_hash)
        if existing_doc:
            logging.info(f"Duplicate image skipped: {filename}")
            return existing_doc

        try:
            # 2. Upload to Storage
            mime_type, _ = mimetypes.guess_type(filename)
            storage_key = self.storage_service.upload_document(
                company_short_name=company.short_name,
                file_content=content,
                filename=filename,
                mime_type=mime_type or "image/jpeg"
            )

            # get signed URL for the uploaded file
            presigned_url = self.storage_service.generate_presigned_url(company.short_name, storage_key)

            # 3. Generate Embedding (using the visual provider logic)
            vector = self.embedding_service.embed_image(
                company_short_name=company.short_name,
                presigned_url=presigned_url,
                image_bytes=content)

            # 4. Extract Meta (Width/Height) - Optional/Lazy load
            image_meta = self._extract_image_meta(content)
            if metadata:
                image_meta.update(metadata)

            # 5. Create Document Record
            new_doc = Document(
                company_id=company.id,
                collection_type_id=collection_type_id,
                filename=filename,
                hash=file_hash,
                user_identifier=user_identifier,
                content="",                         # No text content for images
                storage_key=storage_key,
                meta=image_meta,
                status=DocumentStatus.ACTIVE        # Ready immediately
            )
            # Save document first to get ID
            self.document_repo.insert(new_doc)

            # 6. Create VSImage Record
            vs_image = VSImage(
                company_id=company.id,
                document_id=new_doc.id,
                embedding=vector,
            )
            self.vs_repo.add_image(vs_image)

            logging.info(f"Successfully ingested image {filename}.")

            return new_doc

        except Exception as e:
            logging.exception(f"Error ingesting image {filename}: {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR, str(e))


    def search_similar_images(self,
                              company_short_name: str,
                              image_content: bytes,
                              n_results: int = 5,
                              collection: str = None
                              ) -> list[dict]:
        """
        Searches for images visually similar to the provided image content.
        """
        if not image_content:
            return []

        # 1. Query Repo using the new method
        results = self.vs_repo.query_images_by_image(
            company_short_name=company_short_name,
            image_bytes=image_content,
            n_results=n_results,
            collection_id=self.document_repo.get_collection_type_by_name(company_short_name, collection)
        )

        # 2. Format Results (Reuse logic or refactor to helper)
        return self._format_search_results(company_short_name, results)

    def search_images(self,
                      company_short_name: str,
                      query: str,
                      n_results: int = 5,
                      collection: str = None
                      ) -> list[dict]:
        """
        Searches for images semantically similar to the query text.
        """
        if not query:
            return []

        # obtain collection_id from collection_name
        collection_id = self.document_repo.get_collection_type_by_name(company_short_name, collection)

        results = self.vs_repo.query_images(
            company_short_name=company_short_name,
            query_text=query,
            n_results=n_results,
            collection_id=collection_id
        )
        return self._format_search_results(company_short_name, results)


    def _format_search_results(self, company_short_name: str, results: list) -> list[dict]:
        formatted_results = []
        for item in results:
            if item.get('storage_key'):
                url = self.storage_service.generate_presigned_url(
                    company_short_name,
                    item['storage_key']
                )
            else:
                url = None

            formatted_results.append({
                "id": item['document_id'],
                "filename": item['filename'],
                "url": url,
                "score": item['score'],
                "meta": item['meta']
            })
        return formatted_results

    def _extract_image_meta(self, content: bytes) -> dict:
        try:
            from PIL import Image
            import io
            with Image.open(io.BytesIO(content)) as img:
                return {
                    "width": img.width,
                    "height": img.height,
                    "format": img.format
                }
        except ImportError:
            return {}
        except Exception:
            return {}
