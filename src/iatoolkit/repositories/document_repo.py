# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.models import Document, Company, CollectionType

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

    def get_collection_type_by_name(self, company_short_name: str, collection_name: str) -> Optional[int]:
        if not collection_name:
            return None

        ct = self.session.query(CollectionType).join(Company).filter(
            Company.short_name == company_short_name,
            CollectionType.name == collection_name.lower()
        ).first()
        return ct.id if ct else None

    def commit(self):
        self.session.commit()