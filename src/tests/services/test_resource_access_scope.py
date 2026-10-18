import pytest

from iatoolkit.common.access import Access
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import CollectionType, Company, Document, KnowledgeWiki
from iatoolkit.services.resource_access_scope import ResourceAccessScope


class Decider:
    """Ana may not use: tool 'secret_tool', SQL 'rrhh', collection 'Personas', wiki 'directorio'."""
    DENIED = {("tool", "secret_tool"), ("sql_source", "rrhh"), ("rag_collection", "Personas"),
              ("knowledge_wiki", "directorio")}

    def can(self, company, user, level, rtype, key=None, path=None):
        return (rtype, key) not in self.DENIED

    def is_owner(self, company, user):
        return False

    def effective_role(self, company, user):
        return "user"


class TestResourceAccessScope:
    def setup_method(self):
        Access.register(Decider())
        self.db = DatabaseManager("sqlite:///:memory:")
        self.db.create_all()
        session = self.db.get_session()
        company = Company(short_name="acme", name="Acme")
        session.add(company)
        session.flush()
        for name in ("Contratos", "Personas"):
            session.add(CollectionType(company_id=company.id, name=name))
        session.flush()
        personas = session.query(CollectionType).filter_by(name="Personas").one()
        session.add(Document(id=7, company_id=company.id, collection_type_id=personas.id, filename="sueldos.pdf"))
        for key in ("kb", "directorio"):
            session.add(KnowledgeWiki(company_id=company.id, wiki_key=key, name=key, root_storage_key=key, settings={}))
        session.commit()
        self.scope = ResourceAccessScope(self.db)

    def teardown_method(self):
        Access.clear()

    def call(self, function_name, **arguments):
        return self.scope.scope_tool_call("acme", function_name, "ana@acme.cl", arguments)

    def test_a_tool_the_person_may_not_use_is_refused(self):
        with pytest.raises(IAToolkitException):
            self.call("secret_tool")
        assert self.call("other_tool", x=1) == {"x": 1}

    def test_sql_follows_the_source(self):
        with pytest.raises(IAToolkitException):
            self.call("iat_sql_query", database_key="rrhh", query="select 1")
        assert self.call("iat_sql_query", database_key="ventas", query="select 1")["database_key"] == "ventas"

    def test_a_search_with_no_collection_reaches_only_what_the_person_sees(self):
        assert self.call("iat_document_search", query="x")["collection"] == ["Contratos"]
        with pytest.raises(IAToolkitException):
            self.call("iat_document_search", query="x", collection=["Contratos", "Personas"])
        assert self.call("iat_document_list")["collection"] == "Contratos"

    def test_reading_a_document_follows_its_collection(self):
        with pytest.raises(IAToolkitException):
            self.call("iat_document_read", document_id=7)

    def test_wikis_are_narrowed_or_refused(self):
        assert self.call("iat_wiki_search", query="x")["allowed_wiki_keys"] == ["kb"]
        with pytest.raises(IAToolkitException):
            self.call("iat_wiki_get_page", wiki_key="directorio", path="/")

    def test_nothing_is_scoped_without_a_person(self):
        assert self.scope.scope_tool_call("acme", "secret_tool", None, {"a": 1}) == {"a": 1}

    def test_nothing_restricted_leaves_the_call_as_it_came(self):
        Access.register(type("Open", (Decider,), {"DENIED": set()})())
        assert self.call("iat_document_search", query="x") == {"query": "x"}
        assert self.scope.allowed_collections("acme", "ana@acme.cl") is None
