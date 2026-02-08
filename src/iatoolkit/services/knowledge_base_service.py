# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.


from iatoolkit.repositories.models import Document, VSDoc, Company, DocumentStatus
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.repositories.vs_repo import VSRepo
from iatoolkit.repositories.models import CollectionType
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.parsers.parsing_service import ParsingService
from langchain_text_splitters import RecursiveCharacterTextSplitter
from iatoolkit.services.visual_kb_service import VisualKnowledgeBaseService
from sqlalchemy import desc
from typing import Any
import json
from iatoolkit.common.exceptions import IAToolkitException
import logging
import hashlib
from typing import List, Optional, Union
from datetime import datetime
from injector import inject


class KnowledgeBaseService:
    """
    Central service for managing the RAG (Retrieval-Augmented Generation) Knowledge Base.
    Orchestrates ingestion (OCR -> Split -> Embed -> Store), retrieval, and management.
    """

    @inject
    def __init__(self,
                 document_repo: DocumentRepo,
                 vs_repo: VSRepo,
                 visual_kb_service: VisualKnowledgeBaseService,
                 parsing_service: ParsingService,
                 storage_service: StorageService,
                 profile_service: ProfileService,
                 i18n_service: I18nService):
        self.document_repo = document_repo
        self.vs_repo = vs_repo
        self.visual_kb_service = visual_kb_service
        self.parsing_service = parsing_service
        self.storage_service = storage_service
        self.profile_service = profile_service
        self.i18n_service = i18n_service

        # Configure LangChain for intelligent text splitting
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100,
            separators=["\n\n", "\n", ".", " ", ""]
        )

    def ingest_document_sync(self,
                             company: Company,
                             filename: str,
                             content: bytes,
                             user_identifier: str = None,
                             metadata: dict = None,
                             collection: str = None) -> Document:
        """
        Synchronously processes a document through the entire RAG pipeline:
        1. Saves initial metadata and raw content reference to the SQL Document table.
        2. Parses content via configured parsing provider (docling/legacy/custom).
        3. Splits the text into semantic chunks using LangChain.
        4. Vectorizes and saves chunks to the Vector Store (VSRepo).
        5. Updates the document status to ACTIVE or FAILED.

        Args:
            company: The company owning the document.
            filename: Original filename.
            content: Raw bytes of the file.
            metadata: Optional dictionary with additional info (e.g., document_type).

        Returns:
            The created Document object.
        """
        if not metadata:
            metadata = {}

        # --- Logic for Collection ---
        # priority: 1. method parameter 2. metadata
        collection_name = collection or metadata.get('collection')
        collection_id = self.document_repo.get_collection_id_by_name(company.short_name, collection_name)

        # ---  Router ---
        import mimetypes
        mime_type, _ = mimetypes.guess_type(filename)

        if mime_type and mime_type.startswith('image/'):
            return self.visual_kb_service.ingest_image_sync(
                company=company,
                filename=filename,
                content=content,
                user_identifier=user_identifier,
                metadata=metadata,
                collection_type_id=collection_id
            )
        # 1. Calculate SHA-256 hash of the content
        file_hash = hashlib.sha256(content).hexdigest()

        # 2. Check for duplicates by HASH (Content deduplication)
        # If the same content exists (even with a different filename), we skip processing.
        existing_doc = self.document_repo.get_by_hash(company.id, file_hash)
        if existing_doc:
            if existing_doc.status == DocumentStatus.FAILED:
                # If the previous ingestion failed, we delete the failed document and try again.
                self.delete_document(existing_doc.id)
            else:
                msg = self.i18n_service.t('rag.ingestion.duplicate', filename=filename, company_short_name=company.short_name)
                logging.info(msg)
                return existing_doc


        # 3. Storage creation record with PENDING status
        try:
            # Upload to Storage immediately instead of saving b64 to DB
            # Determine basic mime type for upload
            import mimetypes
            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                mime_type = "application/octet-stream"

            storage_key = self.storage_service.upload_document(
                company_short_name=company.short_name,
                file_content=content,
                filename=filename,
                mime_type=mime_type
            )

            new_doc = Document(
                company_id=company.id,
                collection_type_id=collection_id,
                filename=filename,
                hash=file_hash,
                user_identifier=user_identifier,
                content="",                     # Will be populated after text extraction
                storage_key=storage_key,        # Reference to cloud storage
                meta=metadata,
                status=DocumentStatus.PENDING
            )

            self.document_repo.insert(new_doc)

            # 3. Start processing (Extraction + Vectorization)
            self._process_document_content(company, new_doc, content)

            return new_doc

        except Exception as e:
            logging.exception(f"Error initializing document ingestion for {filename}: {e}")
            error_msg = self.i18n_service.t('rag.ingestion.failed', error=str(e))

            raise IAToolkitException(IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR, error_msg)


    def _process_document_content(self,
                                  company: Company,
                                  document: Document,
                                  raw_content: bytes):
        """
        Internal method to handle the heavy lifting of extraction and vectorization.
        Updates the document status directly via the session.
        """
        session = self.document_repo.session

        try:
            # A. Update status to PROCESSING
            document.status = DocumentStatus.PROCESSING
            session.commit()

            # B. Provider-based parsing (docling/legacy/custom)
            parse_result = self.parsing_service.parse_document(
                company_short_name=company.short_name,
                filename=document.filename,
                content=raw_content,
                metadata=document.meta or {},
                collection_id=document.collection_type_id,
                document_id=document.id,
            )

            extracted_text = "\n\n".join([item.text for item in parse_result.texts if item.text]).strip()
            if not extracted_text and parse_result.tables:
                extracted_text = "\n\n".join([item.text for item in parse_result.tables if item.text]).strip()

            # Backward compatibility until document.content is removed in phase 2
            document.content = extracted_text or ""

            # Persist parser traceability
            doc_meta = dict(document.meta or {})
            doc_meta["parser_provider"] = parse_result.provider
            if parse_result.provider_version:
                doc_meta["parser_version"] = parse_result.provider_version
            if parse_result.warnings:
                doc_meta["parser_warnings"] = parse_result.warnings
            document.meta = doc_meta

            # C. Splitting & chunking
            vs_docs = []
            block_index = 0
            n_images = 0
            n_tables = 0

            text_docs, block_index = self._create_text_chunks(document, parse_result.texts, block_index)
            vs_docs.extend(text_docs)

            table_docs, block_index, n_tables = self._create_table_chunks(document, parse_result.tables, block_index)
            vs_docs.extend(table_docs)

            # E. Add chunks to vector storage
            if vs_docs:
                self.vs_repo.add_document(company.short_name, vs_docs)

            # F. Image ingestion
            n_images = self._ingest_parsed_images(company, document, parse_result.images)

            # G. Finalize
            document.status = DocumentStatus.ACTIVE
            session.commit()
            logging.info(f"Successfully ingested {document.description} with {len(vs_docs)} chunks, {n_images} images, {n_tables} tables.")

        except Exception as e:
            session.rollback()
            logging.error(f"Failed to process document {document.id}: {e}")

            # Attempt to save the error state
            try:
                session.add(document)
                document.status = DocumentStatus.FAILED
                document.error_message = str(e)
                session.commit()
            except:
                pass  # If error commit fails, we can't do much more

            error_msg = self.i18n_service.t('rag.ingestion.processing_failed', error=str(e))
            raise IAToolkitException(IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR, error_msg)

    def _create_text_chunks(self, document: Document, parsed_texts, start_block_index: int) -> tuple[List[VSDoc], int]:
        """Helper 1: Creates text chunks from parser result."""
        vs_docs = []
        block_index = start_block_index

        for item in parsed_texts:
            if not item.text:
                continue
            chunks = self.text_splitter.split_text(item.text)
            for chunk_index, chunk_text in enumerate(chunks):
                meta = {
                    "source_type": "text",
                    "block_index": block_index,
                    "chunk_index": chunk_index
                }
                if document.meta:
                    meta.update(document.meta)

                if item.meta:
                    meta.update(item.meta)
                vs_docs.append(VSDoc(
                    company_id=document.company_id,
                    document_id=document.id,
                    text=chunk_text,
                    meta=meta
                ))
            block_index += 1
        return vs_docs, block_index

    def _create_table_chunks(self, document: Document, parsed_tables, start_block_index: int) -> tuple[List[VSDoc], int, int]:
        """Helper 2: Creates chunks for parsed tables."""
        vs_docs = []
        block_index = start_block_index
        n_tables = 0

        for table_index, table in enumerate(parsed_tables, start=1):
            n_tables += 1

            # 1. Sanitize the JSON to remove heavy visual metadata (bbox, coords)
            clean_json = self._sanitize_table_data(table.table_json)

            # 2. Use provider text, fallback to clean JSON string
            table_text = table.text or json.dumps(clean_json, ensure_ascii=False)
            if not table_text:
                continue

            # 3. Serialize clean JSON for metadata
            table_json_str = json.dumps(clean_json, ensure_ascii=False) if clean_json else None

            # Every table in its own chunk
            meta = {
                "source_type": "table",
                "table_index": table_index,
                "table_json": table_json_str,
                "block_index": block_index,
            }
            if document.meta:
                meta.update(document.meta)

            if table.meta:
                meta.update(table.meta)

            vs_docs.append(VSDoc(
                company_id=document.company_id,
                document_id=document.id,
                text=table_text,
                meta=meta
            ))
            block_index += 1

        return vs_docs, block_index, n_tables

    def _sanitize_table_data(self, data: Any) -> Any:
        """
        Recursively removes heavy visual metadata (bbox, coords) from table JSON.
        Reduces metadata size by ~80-90%.
        """
        keys_to_remove = {
            'bbox', 'coord_origin', 'start_row_offset_idx', 'end_row_offset_idx',
            'start_col_offset_idx', 'end_col_offset_idx', 'fillable', 'row_section'
        }

        if isinstance(data, dict):
            return {
                k: self._sanitize_table_data(v)
                for k, v in data.items()
                if k not in keys_to_remove
            }
        elif isinstance(data, list):
            return [self._sanitize_table_data(item) for item in data]
        else:
            return data

    def _ingest_parsed_images(self, company: Company, document: Document, parsed_images) -> int:
        """Helper 3: Ingests normalized images returned by a parsing provider."""
        n_images = 0
        for image in parsed_images:
            try:
                self.visual_kb_service.ingest_document_image_sync(
                    company=company,
                    parent_document=document,
                    filename=image.filename,
                    content=image.content,
                    page=(image.meta or {}).get("page"),
                    image_index=(image.meta or {}).get("image_index"),
                    metadata=image.meta or {}
                )
                n_images += 1
            except Exception as e:
                logging.warning(f"Failed to ingest image {image.filename}: {e}")
        return n_images


    def search(self,
               company_short_name: str,
               query: str,
               n_results: int = 5,
               collection: str = None,
               metadata_filter: dict = None
               ):
        """
        Performs a semantic search and returns the list of Document objects (chunks).
        Useful for UI displays where structured data is needed instead of a raw string context.

        Args:
            company_short_name: The target company.
            query: The user's question or search term.
            n_results: Max number of chunks to retrieve.
            metadata_filter: Optional filter for document metadata.
            collection: Optional collection name.

        Returns:
            List of Document objects found.
        """
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            # We return empty list instead of error string for consistency
            logging.warning(f"Company {company_short_name} not found during raw search.")
            return []

        # If collection name provided, resolve to ID or handle in VSRepo
        collection_id = self.document_repo.get_collection_id_by_name(company.short_name, collection)

        # Queries VSRepo directly
        chunk_list = self.vs_repo.query(
            company_short_name=company_short_name,
            query_text=query,
            n_results=n_results,
            metadata_filter=metadata_filter,
            collection_id=collection_id,
        )

        return chunk_list

    def list_documents(self,
                       company_short_name: str,
                       status: Optional[Union[str, List[str]]] = None,
                       user_identifier: Optional[str] = None,
                       collection: str = None,
                       filename_keyword: Optional[str] = None,
                       from_date: Optional[datetime] = None,
                       to_date: Optional[datetime] = None,
                       limit: int = 100,
                       offset: int = 0) -> List[Document]:
        """
        Retrieves a paginated list of documents based on various filters.
        Used by the frontend to display the Knowledge Base grid.

        Args:
            company_short_name: Required. Filters by company.
            status: Optional status enum value or list of values (e.g. 'active' or ['active', 'failed']).
            user_identifier: Optional. Filters by the user who uploaded the document.
            filename_keyword: Optional substring to search in filename.
            from_date: Optional start date filter (created_at).
            to_date: Optional end date filter (created_at).
            limit: Pagination limit.
            offset: Pagination offset.

        Returns:
            List of Document objects matching the criteria.
        """
        session = self.document_repo.session

        # Start building the query
        query = session.query(Document).join(Company).filter(Company.short_name == company_short_name)

        # Filter by status (single string or list)
        if status:
            if isinstance(status, list):
                query = query.filter(Document.status.in_(status))
            else:
                query = query.filter(Document.status == status)

        # filter by collection
        if collection:
            query = query.join(Document.collection_type).filter(CollectionType.name == collection.lower())

        # Filter by user identifier
        if user_identifier:
            query = query.filter(Document.user_identifier.ilike(f"%{user_identifier}%"))

        if filename_keyword:
            # Case-insensitive search
            query = query.filter(Document.filename.ilike(f"%{filename_keyword}%"))

        if from_date:
            query = query.filter(Document.created_at >= from_date)

        if to_date:
            query = query.filter(Document.created_at <= to_date)

        # Apply sorting (newest first) and pagination
        query = query.order_by(desc(Document.created_at))
        query = query.limit(limit).offset(offset)

        return query.all()

    def get_document_content(self, document_id: int) -> tuple[bytes, str]:
        """
        Retrieves the raw content of a document and its filename.

        Args:
            document_id: ID of the document.

        Returns:
            A tuple containing (file_bytes, filename).
            Returns (None, None) if document not found.
        """
        doc = self.document_repo.get_by_id(document_id)
        if not doc:
            return None, None

        try:
            # Try to fetch from Cloud Storage
            if doc.storage_key:
                file_bytes = self.storage_service.get_document_content(doc.company.short_name, doc.storage_key)
                return file_bytes, doc.filename

        except Exception as e:
            logging.error(f"Error decoding content for document {document_id}: {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_FORMAT_ERROR,
                        f"Error reading file content: {e}")

    def delete_document(self, document_id: int) -> bool:
        """
        Deletes a document and its associated vectors.
        Since vectors are linked via FK with ON DELETE CASCADE, deleting the Document record is sufficient.
        Also attempts to delete the physical file from Cloud Storage if it exists.

        Args:
            document_id: The ID of the document to delete.

        Returns:
            True if deleted, False if not found.
        """
        doc = self.document_repo.get_by_id(document_id)
        if not doc:
            return False

        session = self.document_repo.session
        try:
            # 1. Delete from Cloud Storage
            # We do this before DB commit. If it fails, we might still want to delete the DB record
            # or rollback. Here I choose to log and proceed, to avoid DB inconsistencies if S3 is down.
            if doc.storage_key:
                try:
                    self.storage_service.delete_file(doc.company.short_name, doc.storage_key)
                except Exception as e:
                    logging.error(f"Failed to delete file from storage for doc {doc.id}: {e}")
                    # We proceed to delete from DB to avoid "ghost" documents in UI

            # 2. delete from database
            session.delete(doc)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logging.error(f"Error deleting document {document_id}: {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
                                     f"Error deleting document: {e}")

    def sync_collection_types(self, company_short_name: str, categories_config: list):
        """
        This should be called during company initialization or configuration reload.
        Syncs DB collection types with the provided list.
        Also updates the configuration YAML.
        """
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                                     f'Company {company_short_name} not found')

        session = self.document_repo.session

        # 1. Get existing types
        existing_types = session.query(CollectionType).filter_by(company_id=company.id).all()
        existing_names = {ct.name.lower(): ct for ct in existing_types}

        # 2. Add new types
        current_config_names = set()
        for cat_name in categories_config:
            current_config_names.add(cat_name)
            if cat_name not in existing_names:
                new_type = CollectionType(company_id=company.id, name=cat_name.lower())
                session.add(new_type)

        session.commit()


    def get_collection_names(self, company_short_name: str) -> List[str]:
        """
        Retrieves the names of all collections defined for a specific company.
        """
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            logging.warning(f"Company {company_short_name} not found when listing collections.")
            return []

        session = self.document_repo.session
        collections = session.query(CollectionType).filter_by(company_id=company.id).all()
        return [c.name for c in collections]
