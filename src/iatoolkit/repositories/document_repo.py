# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.models import Document, DocumentImage, Company, CollectionType

from injector import inject
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.common.exceptions import IAToolkitException
from typing import List, Optional


class DocumentRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

    def insert(self,new_document: Document):
        self.session.add(new_document)
        self.session.commit()
        return new_document

    def insert_document_image(self, document_image: DocumentImage) -> DocumentImage:
        self.session.add(document_image)
        self.session.commit()
        return document_image

    def get(self, company_id, filename: str ) -> Document:
        if not company_id or not filename:
            raise IAToolkitException(IAToolkitException.ErrorType.PARAM_NOT_FILLED,
                               'missing company_id or filename')

        return self.session.query(Document).filter_by(company_id=company_id, filename=filename).first()

    def get_by_hash(self, company_id: int, file_hash: str) -> Document:
        """Find a document by its content hash within a company."""
        if not company_id or not file_hash:
            return None

        return self.session.query(Document).filter_by(company_id=company_id, hash=file_hash).first()

    def get_by_id(self, document_id: int) -> Document:
        if not document_id:
            return None

        return self.session.query(Document).filter_by(id=document_id).first()

    def get_collection_id_by_name(self, company_short_name: str, collection_name: str) -> Optional[int]:
        if not collection_name:
            return None

        ct = self.session.query(CollectionType).join(Company).filter(
            Company.short_name == company_short_name,
            CollectionType.name == collection_name.strip().lower()
        ).first()
        return ct.id if ct else None

    def get_collection_ids_by_name(self, company_short_name: str, collection_names: List[str]) -> List[int]:
        if not collection_names:
            return []

        normalized_names = []
        for name in collection_names:
            if not isinstance(name, str):
                continue
            normalized = name.strip().lower()
            if normalized and normalized not in normalized_names:
                normalized_names.append(normalized)

        if not normalized_names:
            return []

        collections = self.session.query(CollectionType).join(Company).filter(
            Company.short_name == company_short_name,
            CollectionType.name.in_(normalized_names)
        ).all()

        collection_ids_by_name = {collection.name: collection.id for collection in collections}
        return [collection_ids_by_name[name] for name in normalized_names if name in collection_ids_by_name]

    def get_collection_by_name(self, company_short_name: str, collection_name: str) -> Optional[CollectionType]:
        if not collection_name:
            return None

        return self.session.query(CollectionType).join(Company).filter(
            Company.short_name == company_short_name,
            CollectionType.name == collection_name.strip().lower()
        ).first()

    def get_collection_by_id(self, collection_id) -> Optional[CollectionType]:
        if not collection_id:
            return None

        return self.session.query(CollectionType).filter_by(id=collection_id).first()

    def list_documents_by_collection(self, company_id: int, collection_id: int) -> List[Document]:
        if not company_id or not collection_id:
            return []

        return (
            self.session.query(Document)
            .filter_by(company_id=company_id, collection_type_id=collection_id)
            .order_by(Document.created_at.asc(), Document.id.asc())
            .all()
        )

    def commit(self):
        self.session.commit()
