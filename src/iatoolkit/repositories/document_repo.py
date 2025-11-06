# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.models import Document
from injector import inject
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.common.exceptions import IAToolkitException


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

    def get_by_id(self, document_id: int) -> Document:
        if not document_id:
            return None

        return self.session.query(Document).filter_by(id=document_id).first()
