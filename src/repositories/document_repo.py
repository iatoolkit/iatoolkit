# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

from repositories.models import Document
from repositories.models import Company
from injector import inject
from repositories.database_manager import DatabaseManager
from common.exceptions import IAToolkitException


class DocumentRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

    def insert(self,new_document: Document):
        self.session.add(new_document)
        self.session.commit()
        return new_document

    def get(self, company: Company, filename: str ) -> Document:
        if not company or not filename:
            raise IAToolkitException(IAToolkitException.ErrorType.PARAM_NOT_FILLED,
                               'Falta empresa o filename')

        return self.session.query(Document).filter_by(company_id=company.id, filename=filename).first()

    def get_by_id(self, document_id: int) -> Document:
        if not document_id:
            return None

        return self.session.query(Document).filter_by(id=document_id).first()
