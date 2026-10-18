# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""Who may do what: the one question every check asks (BL-010, Fase 1).

Code never names a role. It asks whether a principal (a person's email, or a
service account `service:<key>`) has a level over a resource:

    access.can(company, user_identifier, EDIT, "company")
    access.can(company, user_identifier, USE, "agent", "cobranza")

Three levels, each including the one below:
    1 USE    use an agent, tool, model, SQL source / see content
    2 EDIT   change the resource (an agent's prompt, a folder's documents)
    3 ADMIN  decide on it: who has access, delete it, its settings

Over the resource type "company", EDIT is entering the admin console and
editing every resource, and ADMIN is administering the company (its team,
settings). Billing and deleting the tenant are for its owners only (`is_owner`).

Enterprise registers the decider backed by groups and grants. Without it,
the decision falls back to the person's role in the company, as before.
"""

from __future__ import annotations

import logging
from typing import Callable, Protocol

USE = 1
EDIT = 2
ADMIN = 3

LEVEL_NAMES = {USE: "use", EDIT: "edit", ADMIN: "admin"}

# The level each legacy role holds over everything (core without enterprise).
ROLE_LEVELS = {"user": USE, "editor": EDIT, "admin": ADMIN, "owner": ADMIN}


class AccessDecider(Protocol):
    def can(self, company_short_name: str, user_identifier: str | None, level: int,
            resource_type: str, resource_key: str | None = None,
            resource_path: str | None = None) -> bool: ...

    def is_owner(self, company_short_name: str, user_identifier: str | None) -> bool: ...

    def effective_role(self, company_short_name: str, user_identifier: str | None) -> str | None: ...


class RoleAccessDecider:
    """Core's fallback: the role of iat_user_company grants its level over everything."""

    def __init__(self, role_reader: Callable[[str, str], str | None]):
        self.role_reader = role_reader

    def _role(self, company_short_name, user_identifier) -> str | None:
        if not user_identifier:
            return None
        return self.role_reader(company_short_name, user_identifier)

    def can(self, company_short_name, user_identifier, level, resource_type, resource_key=None,
            resource_path=None) -> bool:
        if level <= USE and resource_type != "company":
            # Without groups nothing is restricted: whoever enters the company uses
            # what it offers (members, and the end users a key acts for).
            return True
        role = self._role(company_short_name, user_identifier)
        if role is None:
            return False
        return ROLE_LEVELS.get(role, USE) >= level

    def is_owner(self, company_short_name, user_identifier) -> bool:
        return self._role(company_short_name, user_identifier) == "owner"

    def effective_role(self, company_short_name, user_identifier) -> str | None:
        return self._role(company_short_name, user_identifier)


class Access:
    """The registered decider; enterprise replaces core's fallback at boot."""

    _decider: AccessDecider | None = None

    @classmethod
    def register(cls, decider: AccessDecider) -> None:
        cls._decider = decider

    @classmethod
    def clear(cls) -> None:
        cls._decider = None

    @classmethod
    def registered(cls) -> bool:
        """Whether a decider other than core's role fallback is in place (enterprise)."""
        return cls._decider is not None and not isinstance(cls._decider, RoleAccessDecider)

    @classmethod
    def decider(cls) -> AccessDecider:
        if cls._decider is None:
            cls._decider = RoleAccessDecider(_role_from_profile_service)
        return cls._decider


def decider_for(role_reader: Callable[[str, str], str | None]) -> AccessDecider:
    """The registered decider, or the role fallback reading roles with `role_reader`
    (views that already hold a ProfileRepo)."""
    return Access.decider() if Access.registered() else RoleAccessDecider(role_reader)


def _role_from_profile_service(company_short_name: str, user_identifier: str) -> str | None:
    from iatoolkit import current_iatoolkit
    from iatoolkit.services.profile_service import ProfileService

    return current_iatoolkit().get_injector().get(ProfileService).get_role_in_company(
        company_short_name, user_identifier)


def can(company_short_name: str, user_identifier: str | None, level: int, resource_type: str,
        resource_key: str | None = None, resource_path: str | None = None) -> bool:
    try:
        return bool(Access.decider().can(company_short_name, user_identifier, level, resource_type,
                                         resource_key, resource_path))
    except Exception as exc:
        # Deciding failed: deny, never fall open.
        logging.warning("Access check failed (%s, %s, %s %s): %s", company_short_name, user_identifier,
                        level, resource_type, exc)
        return False


def is_owner(company_short_name: str, user_identifier: str | None) -> bool:
    try:
        return bool(Access.decider().is_owner(company_short_name, user_identifier))
    except Exception as exc:
        logging.warning("Owner check failed (%s, %s): %s", company_short_name, user_identifier, exc)
        return False


def effective_roles(company_short_name: str, user_identifiers: list[str]) -> dict[str, str | None]:
    """`effective_role` for many people at once (the Users screen)."""
    decider = Access.decider()
    try:
        bulk = getattr(decider, "effective_roles", None)
        if callable(bulk):
            return bulk(company_short_name, user_identifiers)
        return {u: decider.effective_role(company_short_name, u) for u in user_identifiers}
    except Exception as exc:
        logging.warning("Effective roles failed (%s): %s", company_short_name, exc)
        return {}


def effective_role(company_short_name: str, user_identifier: str | None) -> str | None:
    """What the person can do over the company, as the console's old role names.

    Only for screens that still show or branch on a role name (labels, menus);
    access is always decided with `can`.
    """
    try:
        return Access.decider().effective_role(company_short_name, user_identifier)
    except Exception as exc:
        logging.warning("Effective role failed (%s, %s): %s", company_short_name, user_identifier, exc)
        return None


def role_assigned(company_short_name: str, user_identifier: str, role: str) -> None:
    """Somebody was given a legacy role (signup's bootstrap admin, company activation,
    `init-install --owner`): the registered decider puts them in the matching group."""
    decider = Access._decider
    hook = getattr(decider, "role_assigned", None) if decider is not None else None
    if callable(hook):
        try:
            hook(company_short_name, user_identifier, role)
        except Exception as exc:
            logging.warning("Role %s of %s in %s not moved to its group: %s", role, user_identifier,
                            company_short_name, exc)


def filter_llm_models(company_short_name: str, user_identifier: str | None, default_model: str | None,
                      models: list[dict]) -> tuple[str | None, list[dict]]:
    """The chat's model choice limited to the models this person may use (BL-010, Fase 2).

    When the company's default is not among them, the first one they may use becomes
    their default."""
    if not user_identifier or not Access.registered():
        return default_model, models
    allowed = [m for m in models or [] if can(company_short_name, user_identifier, USE, "model",
                                              str((m or {}).get("id") or ""))]
    allowed_ids = [str(m.get("id")) for m in allowed]
    if default_model and default_model not in allowed_ids:
        default_model = allowed_ids[0] if allowed_ids else None
    return default_model, allowed


def stamp(company_short_name: str) -> str | None:
    """A value that changes whenever the company's groups, members or grants change.

    A person's chat context is built once and cached; when this changes, it is rebuilt
    so the tools, SQL schema and collections it describes follow the new access."""
    decider = Access._decider
    hook = getattr(decider, "stamp", None) if decider is not None else None
    if not callable(hook):
        return None
    try:
        return hook(company_short_name)
    except Exception as exc:
        logging.warning("Access stamp of %s not read: %s", company_short_name, exc)
        return None


def sql_table_filter(company_short_name: str, user_identifier: str | None):
    """`fn(database, table) -> bool` for the SQL schema shown to this person, or None.

    Some SQL sources hold resources of their own (enterprise's knowledge tables): the
    decider names their resource type, and each table needs level 1 over it."""
    decider = Access._decider
    hook = getattr(decider, "sql_table_resource", None) if decider is not None else None
    if not user_identifier or not callable(hook):
        return None

    def allowed(database: str, table: str) -> bool:
        resource_type = hook(company_short_name, database)
        return not resource_type or can(company_short_name, user_identifier, USE, resource_type, table)
    return allowed


def person_can(company_short_name: str, auth_result: dict | None, level: int, resource_type: str = "company",
               resource_key: str | None = None) -> bool:
    """A signed-in person's access, from an AuthService result.

    Only sessions carry `user_role`; an API key is not a person and gets False
    (each view decides on its own whether a key may pass).
    """
    if not isinstance(auth_result, dict) or "user_role" not in auth_result:
        return False
    if not Access.registered():
        # Core alone: the session's role was just read from iat_user_company.
        return _session_role_decider(auth_result).can(company_short_name, auth_result.get("user_identifier") or "session",
                                                       level, resource_type, resource_key)
    return can(company_short_name, auth_result.get("user_identifier"), level, resource_type, resource_key)


def person_is_owner(company_short_name: str, auth_result: dict | None) -> bool:
    if not isinstance(auth_result, dict) or "user_role" not in auth_result:
        return False
    if not Access.registered():
        return _session_role_decider(auth_result).is_owner(company_short_name,
                                                            auth_result.get("user_identifier") or "session")
    return is_owner(company_short_name, auth_result.get("user_identifier"))


def _session_role_decider(auth_result: dict) -> RoleAccessDecider:
    role = str(auth_result.get("user_role") or "").strip().lower() or None
    return RoleAccessDecider(lambda company_short_name, user_identifier: role)
