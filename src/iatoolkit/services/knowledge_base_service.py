# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.


from iatoolkit.repositories.models import Document, VSDoc, Company, DocumentStatus
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.repositories.vs_repo import VSRepo
from iatoolkit.repositories.models import CollectionType
from iatoolkit.services.document_service import DocumentService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.i18n_service import I18nService
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import desc
from typing import Dict
from iatoolkit.common.exceptions import IAToolkitException
import base64
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
                 document_service: DocumentService,
                 profile_service: ProfileService,
                 i18n_service: I18nService):
        self.document_repo = document_repo
        self.vs_repo = vs_repo
        self.document_service = document_service
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
        1. Saves initial metadata and raw content (base64) to the SQL Document table.
        2. Extracts text using DocumentService (handles OCR, PDF, DOCX).
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
        collection_type_id = self._get_collection_type_id(company.id, collection_name)

        # 1. Calculate SHA-256 hash of the content
        file_hash = hashlib.sha256(content).hexdigest()

        # 2. Check for duplicates by HASH (Content deduplication)
        # If the same content exists (even with a different filename), we skip processing.
        existing_doc = self.document_repo.get_by_hash(company.id, file_hash)
        if existing_doc:
            msg = self.i18n_service.t('rag.ingestion.duplicate', filename=filename, company_short_name=company.short_name)
            logging.info(msg)
            return existing_doc


        # 3. Create initial record with PENDING status
        try:
            # Encode to b64 for safe storage in DB if needed later for download
            content_b64 = base64.b64encode(content).decode('utf-8')

            new_doc = Document(
                company_id=company.id,
                collection_type_id=collection_type_id,
                filename=filename,
                hash=file_hash,
                user_identifier=user_identifier,
                content="",         # Will be populated after text extraction
                content_b64=content_b64,
                meta=metadata,
                status=DocumentStatus.PENDING
            )

            self.document_repo.insert(new_doc)

            # 3. Start processing (Extraction + Vectorization)
            self._process_document_content(company.short_name, new_doc, content)

            return new_doc

        except Exception as e:
            logging.exception(f"Error initializing document ingestion for {filename}: {e}")
            error_msg = self.i18n_service.t('rag.ingestion.failed', error=str(e))

            raise IAToolkitException(IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR, error_msg)


    def _process_document_content(self, company_short_name: str, document: Document, raw_content: bytes):
        """
        Internal method to handle the heavy lifting of extraction and vectorization.
        Updates the document status directly via the session.
        """
        session = self.document_repo.session

        try:
            # A. Update status to PROCESSING
            document.status = DocumentStatus.PROCESSING
            session.commit()

            # B. Text Extraction (Uses existing service logic for OCR, etc.)
            extracted_text = self.document_service.file_to_txt(document.filename, raw_content)

            if not extracted_text:
                raise ValueError(self.i18n_service.t('rag.ingestion.empty_text'))

            # Update the extracted content in the original document record
            document.content = extracted_text

            # C. Splitting (LangChain)
            chunks = self.text_splitter.split_text(extracted_text)

            # D. Create VSDocs (Chunks)
            # Note: The embedding generation happens inside VSRepo or can be explicit here
            vs_docs = []
            for chunk_text in chunks:
                vs_doc = VSDoc(
                    company_id=document.company_id,
                    document_id=document.id,
                    text=chunk_text
                )
                vs_docs.append(vs_doc)

            # E. Vector Storage
            # We need the short_name so VSRepo knows which API Key to use for embeddings
            self.vs_repo.add_document(company_short_name, vs_docs)

            # F. Finalize
            document.status = DocumentStatus.ACTIVE
            session.commit()
            logging.info(f"Successfully ingested document {document.id} ({document.collection_type.name}, {document.filename}) with {len(chunks)} chunks.")

        except Exception as e:
            session.rollback()
            logging.error(f"Failed to process document {document.id}: {e}")

            # Attempt to save the error state
            try:
                document.status = DocumentStatus.FAILED
                document.error_message = str(e)
                session.commit()
            except:
                pass  # If error commit fails, we can't do much more

            error_msg = self.i18n_service.t('rag.ingestion.processing_failed', error=str(e))
            raise IAToolkitException(IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR, error_msg)


    def search(self, company_short_name: str, query: str, n_results: int = 5, metadata_filter: dict = None) -> str:
        """
        Performs a semantic search against the vector store and formats the result as a context string for LLMs.
        Replaces the legacy SearchService logic.

        Args:
            company_short_name: The target company.
            query: The user's question or search term.
            n_results: Max number of chunks to retrieve.
            metadata_filter: Optional filter for document metadata.

        Returns:
            Formatted string with context.
        """
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return f"error: {self.i18n_service.t('rag.search.company_not_found', company_short_name=company_short_name)}"

        # Queries VSRepo (which typically uses pgvector/SQL underneath)
        chunk_list = self.vs_repo.query(
            company_short_name=company_short_name,
            query_text=query,
            n_results=n_results,
            metadata_filter=metadata_filter
        )

        search_context = ''
        for chunk in chunk_list:
            # 'doc' here is a reconstructed Document object containing the chunk text
            search_context += f'document "{chunk['filename']}"'

            if chunk.get('meta') and 'document_type' in chunk.get('meta'):
                doc_type = chunk.get('meta').get('document_type', '')
                search_context += f' type: {doc_type}'

            search_context += f': {chunk.get('text')}\n\n'

        return search_context

    def search_raw(self,
                   company_short_name: str,
                   query: str, n_results: int = 5,
                   collection: str = None,
                   metadata_filter: dict = None
                   ) -> List[Dict]:
        """
        Performs a semantic search and returns the list of Document objects (chunks).
        Useful for UI displays where structured data is needed instead of a raw string context.

        Args:
            company_short_name: The target company.
            query: The user's question or search term.
            n_results: Max number of chunks to retrieve.
            metadata_filter: Optional filter for document metadata.

        Returns:
            List of Document objects found.
        """
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            # We return empty list instead of error string for consistency
            logging.warning(f"Company {company_short_name} not found during raw search.")
            return []

        # If collection name provided, resolve to ID or handle in VSRepo
        collection_id = None
        if collection:
            collection_id = self._get_collection_type_id(company.id, collection)
            if not collection_id:
                logging.warning(f"Collection '{collection}' not found. Searching all.")


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
            query = query.join(CollectionType).filter(CollectionType.name == collection)

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
        if not doc or not doc.content_b64:
            return None, None

        try:
            file_bytes = base64.b64decode(doc.content_b64)
            return file_bytes, doc.filename
        except Exception as e:
            logging.error(f"Error decoding content for document {document_id}: {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_FORMAT_ERROR,
                        f"Error reading file content: {e}")

    def delete_document(self, document_id: int) -> bool:
        """
        Deletes a document and its associated vectors.
        Since vectors are linked via FK with ON DELETE CASCADE, deleting the Document record is sufficient.

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
        """
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                            f'Company {company_short_name} not found')


        session = self.document_repo.session
        existing_types = session.query(CollectionType).filter_by(company_id=company.id).all()
        existing_names = {ct.name: ct for ct in existing_types}

        for cat_name in categories_config:
            if cat_name not in existing_names:
                new_type = CollectionType(company_id=company.id, name=cat_name)
                session.add(new_type)

        # Opcional: Eliminar los que ya no están en el config?
        # Por seguridad de datos, mejor no borrar automáticamente, o marcarlos inactivos.

        session.commit()

    def _get_collection_type_id(self, company_id: int, collection_name: str) -> Optional[int]:
        """Helper to get ID by name"""
        if not collection_name:
            return None
        session = self.document_repo.session
        ct = session.query(CollectionType).filter_by(company_id=company_id, name=collection_name).first()
        return ct.id if ct else None
