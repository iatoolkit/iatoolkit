# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import Bridge, Company


class BridgeRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.session = db_manager.get_session()

    def create(self, bridge: Bridge) -> Bridge:
        self.session.add(bridge)
        self.session.commit()
        return bridge

    def update(self, bridge: Bridge) -> Bridge:
        self.session.add(bridge)
        self.session.commit()
        return bridge

    def delete(self, bridge: Bridge):
        self.session.delete(bridge)
        self.session.commit()

    def get_by_company(self, company: Company) -> list[Bridge]:
        return (
            self.session.query(Bridge)
            .filter(Bridge.company_id == company.id)
            .order_by(Bridge.bridge_id.asc())
            .all()
        )

    def get_by_id(self, company: Company, bridge_pk: int) -> Bridge | None:
        return (
            self.session.query(Bridge)
            .filter(Bridge.company_id == company.id, Bridge.id == bridge_pk)
            .first()
        )

    def get_by_bridge_id(self, company: Company, bridge_id: str) -> Bridge | None:
        return (
            self.session.query(Bridge)
            .filter(Bridge.company_id == company.id, Bridge.bridge_id == bridge_id)
            .first()
        )

    def get_by_api_key_id(self, api_key_id: int) -> Bridge | None:
        """
        Resolves the bridge a connecting agent belongs to from the API key it
        authenticated with. This is what replaces deriving the bridge identity
        from the key's name.
        """
        return (
            self.session.query(Bridge)
            .filter(Bridge.api_key_id == api_key_id)
            .first()
        )

    def list_all(self) -> list[tuple[Bridge, Company]]:
        """
        Every bridge across every company, joined with its company. Powers the
        cross-tenant monitoring view in the hosting control center, which is
        the one place that legitimately looks past a single company.
        """
        return (
            self.session.query(Bridge, Company)
            .join(Company, Bridge.company_id == Company.id)
            .order_by(Company.short_name.asc(), Bridge.bridge_id.asc())
            .all()
        )
