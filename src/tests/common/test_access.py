import pytest

from iatoolkit.common import access
from iatoolkit.common.access import ADMIN, EDIT, USE, Access, RoleAccessDecider


@pytest.fixture(autouse=True)
def no_decider():
    Access.clear()
    yield
    Access.clear()


class FakeDecider:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.assigned = []

    def can(self, company, user, level, resource_type, resource_key=None, resource_path=None):
        return self.allowed

    def is_owner(self, company, user):
        return False

    def effective_role(self, company, user):
        return "editor"

    def role_assigned(self, company, user, role):
        self.assigned.append((company, user, role))


class TestRoleFallback:
    """Core without enterprise: the legacy role, and nothing restricted for use."""

    def test_using_is_open_and_the_company_follows_the_role(self):
        roles = {"ana@acme.cl": "user", "eli@acme.cl": "editor", "ad@acme.cl": "admin", "du@acme.cl": "owner"}
        decider = RoleAccessDecider(lambda company, user: roles.get(user))

        assert decider.can("acme", "CRIVOLI", USE, "agent", "cobranza")
        assert not decider.can("acme", "ana@acme.cl", EDIT, "company")
        assert decider.can("acme", "eli@acme.cl", EDIT, "company")
        assert not decider.can("acme", "eli@acme.cl", ADMIN, "company")
        assert decider.can("acme", "ad@acme.cl", ADMIN, "company")
        assert decider.is_owner("acme", "du@acme.cl") and not decider.is_owner("acme", "ad@acme.cl")
        assert not decider.can("acme", "nadie@acme.cl", EDIT, "company")


class TestPersonCan:
    def test_a_session_decides_with_its_role_when_no_decider_is_registered(self):
        auth = {"success": True, "user_identifier": "ad@acme.cl", "user_role": "admin"}

        assert access.person_can("acme", auth, ADMIN)
        assert not access.person_can("acme", {**auth, "user_role": "editor"}, ADMIN)
        assert access.person_is_owner("acme", {**auth, "user_role": "owner"})

    def test_an_api_key_is_not_a_person(self):
        key = {"success": True, "auth_type": "api_key", "user_identifier": "service:erp"}

        assert not access.person_can("acme", key, USE)
        assert not access.person_is_owner("acme", key)

    def test_the_registered_decider_decides_not_the_session_role(self):
        Access.register(FakeDecider(allowed=False))
        auth = {"success": True, "user_identifier": "ad@acme.cl", "user_role": "admin"}

        assert Access.registered()
        assert not access.person_can("acme", auth, ADMIN)


class TestHooks:
    def test_role_assigned_reaches_the_registered_decider(self):
        decider = FakeDecider()
        Access.register(decider)

        access.role_assigned("acme", "ana@acme.cl", "owner")

        assert decider.assigned == [("acme", "ana@acme.cl", "owner")]

    def test_role_assigned_without_a_decider_does_nothing(self):
        access.role_assigned("acme", "ana@acme.cl", "owner")

    def test_a_failing_decider_denies(self):
        class Broken(FakeDecider):
            def can(self, *args, **kwargs):
                raise RuntimeError("db down")

        Access.register(Broken())
        assert access.can("acme", "ana@acme.cl", USE, "agent", "x") is False

    def test_decider_for_falls_back_to_the_given_role_reader(self):
        decider = access.decider_for(lambda company, user: "admin")
        assert decider.can("acme", "ad@acme.cl", ADMIN, "company")

        Access.register(FakeDecider(allowed=False))
        assert not access.decider_for(lambda company, user: "admin").can("acme", "ad@acme.cl", ADMIN, "company")


class TestModels:
    def test_the_chat_offers_only_the_models_the_person_may_use(self):
        class OnlyMini(FakeDecider):
            def can(self, company, user, level, rtype, key=None, path=None):
                return key == "gpt-mini"
        Access.register(OnlyMini())
        models = [{"id": "gpt-big"}, {"id": "gpt-mini"}]

        default, allowed = access.filter_llm_models("acme", "ana@acme.cl", "gpt-big", models)

        assert default == "gpt-mini" and allowed == [{"id": "gpt-mini"}]

    def test_without_groups_the_models_are_unchanged(self):
        models = [{"id": "gpt-big"}]
        assert access.filter_llm_models("acme", "ana@acme.cl", "gpt-big", models) == ("gpt-big", models)

    def test_decision_models_never_reach_the_chat(self):
        decision = {"id": "typesafe/jev-1.14", "capabilities": {"kind": "decision"}}
        models = [decision, {"id": "gpt-big"}]

        default, allowed = access.filter_llm_models("acme", "ana@acme.cl", "typesafe/jev-1.14", models)

        assert allowed == [{"id": "gpt-big"}]
        assert default == "gpt-big"


class TestStampAndTables:
    def test_stamp_and_table_filter_come_from_the_decider(self):
        class WithTables(FakeDecider):
            def stamp(self, company):
                return "abc"

            def sql_table_resource(self, company, database):
                return "knowledge_table" if database == "knowledge_tables" else None

            def can(self, company, user, level, rtype, key=None, path=None):
                return not (rtype == "knowledge_table" and key == "remuneraciones")
        Access.register(WithTables())

        allowed = access.sql_table_filter("acme", "ana@acme.cl")

        assert access.stamp("acme") == "abc"
        assert allowed("knowledge_tables", "ventas") and not allowed("knowledge_tables", "remuneraciones")
        assert allowed("erp", "remuneraciones")

    def test_without_a_decider_nothing_is_filtered(self):
        assert access.stamp("acme") is None
        assert access.sql_table_filter("acme", "ana@acme.cl") is None


class AudienceDecider(FakeDecider):
    def audience_visible(self, company, user, key):
        return user == "ana@acme.cl" and key == "group:rrhh"

    def visible_audiences(self, company, user):
        return ["group:rrhh"] if user == "ana@acme.cl" else []

    def audience_label(self, company, key):
        return {"group:rrhh": "RRHH"}.get(key)

    def audience_for_folder(self, company, folder_id):
        return "memory_folder:3" if folder_id == 3 else None


class BrokenAudienceDecider(FakeDecider):
    def audience_visible(self, *args):
        raise RuntimeError("down")

    def visible_audiences(self, *args):
        raise RuntimeError("down")

    def audience_label(self, *args):
        raise RuntimeError("down")

    def audience_for_folder(self, *args):
        raise RuntimeError("down")


class TestAudiences:
    """Memoria's audiences (BL-010, Fase 3): who reads a page."""

    def test_without_a_decider_everything_is_the_companys(self):
        assert access.audience_visible("acme", "ana@acme.cl", "group:rrhh")
        assert access.visible_audiences("acme", "ana@acme.cl") is None
        assert access.audience_for_folder("acme", 3) is None
        assert access.audience_label("acme", None) is None
        assert access.audience_label("acme", "group:rrhh") == "group:rrhh"

    def test_the_decider_decides_who_reads_an_audience(self):
        Access.register(AudienceDecider())
        assert access.audience_visible("acme", "ana@acme.cl", "group:rrhh")
        assert not access.audience_visible("acme", "luis@acme.cl", "group:rrhh")
        assert access.audience_visible("acme", "luis@acme.cl", None)
        assert access.visible_audiences("acme", "luis@acme.cl") == []
        assert access.audience_label("acme", "group:rrhh") == "RRHH"
        assert access.audience_for_folder("acme", 3) == "memory_folder:3"
        assert access.audience_for_folder("acme", 4) is None

    def test_a_failing_decider_shows_nothing_restricted_and_keeps_new_content_restricted(self):
        Access.register(BrokenAudienceDecider())
        assert not access.audience_visible("acme", "ana@acme.cl", "group:rrhh")
        assert access.visible_audiences("acme", "ana@acme.cl") == []
        assert access.audience_label("acme", "group:rrhh") == "group:rrhh"
        assert access.audience_for_folder("acme", 3) == "memory_folder:3"
