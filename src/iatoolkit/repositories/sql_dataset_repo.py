# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from typing import Optional

from injector import inject

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import SqlDataset


class SqlDatasetRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

    def list_by_company(self, company_id: int, active_only: bool = True) -> list[SqlDataset]:
        query = self.session.query(SqlDataset).filter_by(company_id=company_id)
        if active_only:
            query = query.filter(SqlDataset.is_active.is_(True))
        return query.order_by(SqlDataset.name.asc()).all()

    def get_by_id(self, company_id: int, dataset_id: int) -> Optional[SqlDataset]:
        return self.session.query(SqlDataset).filter_by(company_id=company_id, id=dataset_id).first()

    def get_by_name(self, company_id: int, name: str) -> Optional[SqlDataset]:
        return self.session.query(SqlDataset).filter_by(company_id=company_id, name=name).first()

    def create_or_update(self, dataset: SqlDataset) -> SqlDataset:
        if dataset.id:
            persisted = self.session.merge(dataset)
        else:
            self.session.add(dataset)
            persisted = dataset
        self.session.commit()
        return persisted

    def delete(self, dataset: SqlDataset) -> None:
        self.session.delete(dataset)
        self.session.commit()
