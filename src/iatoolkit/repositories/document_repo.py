# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.models import (Document, CollectionType,
                                IngestionStatus, IngestionSource, IngestionRun )

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

    def get_collection_type_by_name(self, company_id: int, name: str) -> Optional[CollectionType]:
        return self.session.query(CollectionType).filter_by(company_id=company_id, name=name.lower()).first()

    # --- Ingestion Source Methods ---
    def get_ingestion_source_by_name(self, company_id: int, name: str) -> Optional[IngestionSource]:
        return self.session.query(IngestionSource).filter_by(company_id=company_id, name=name).first()

    def get_ingestion_source_by_id(self, company_id: int, source_id: int) -> Optional[IngestionSource]:
        return self.session.query(IngestionSource).filter_by(company_id=company_id, id=source_id).first()

    def list_ingestion_sources(self, company_id: int) -> List[IngestionSource]:
        return self.session.query(IngestionSource).filter_by(company_id=company_id).all()

    def delete_ingestion_source(self, source: IngestionSource) -> None:
        self.session.delete(source)
        self.session.commit()

    def create_or_update_ingestion_source(self, source: IngestionSource) -> IngestionSource:
        """Adds or updates a source. If ID exists, it merges; otherwise adds."""
        if source.id:
            self.session.merge(source)
        else:
            self.session.add(source)
        self.session.commit()
        return source

    def get_active_ingestion_sources(self, company_id: int, names: List[str]) -> List[IngestionSource]:
        """Retrieves active sources matching the given names list."""
        query = self.session.query(IngestionSource).filter(
            IngestionSource.company_id == company_id,
            IngestionSource.name.in_(names),
            IngestionSource.status != IngestionStatus.PAUSED
        )
        return query.all()

    # --- Ingestion Run Methods ---

    def create_ingestion_run(self, run: IngestionRun) -> IngestionRun:
        self.session.add(run)
        self.session.commit()
        return run

    def update_ingestion_run(self, run: IngestionRun) -> IngestionRun:
        self.session.merge(run)
        self.session.commit()
        return run

    def commit(self):
        self.session.commit()