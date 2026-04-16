# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from typing import Optional

from injector import inject

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import SqlSource


class SqlSourceRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

    def list_by_company(self, company_id: int, active_only: bool = True) -> list[SqlSource]:
        query = self.session.query(SqlSource).filter_by(company_id=company_id)
        if active_only:
            query = query.filter(SqlSource.is_active.is_(True))
        return query.order_by(SqlSource.database.asc()).all()

    def get_by_id(self, company_id: int, source_id: int) -> Optional[SqlSource]:
        return self.session.query(SqlSource).filter_by(company_id=company_id, id=source_id).first()

    def get_by_database(self, company_id: int, database: str) -> Optional[SqlSource]:
        return self.session.query(SqlSource).filter_by(company_id=company_id, database=database).first()

    def create_or_update(self, source: SqlSource) -> SqlSource:
        if source.id:
            persisted = self.session.merge(source)
        else:
            self.session.add(source)
            persisted = source
        self.session.commit()
        return persisted

    def delete(self, source: SqlSource) -> None:
        self.session.delete(source)
        self.session.commit()

