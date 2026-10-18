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
