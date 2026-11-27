# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""Who a run without a person acts as (BL-034, R7).

Pipelines, scheduled jobs and other internal runs call tools with no person
behind them. Before R7, a call with no identity at all reached everything in
its company, unchecked. Now every call is checked against an identity's groups
and grants, like a person's:

- a call with no identity acts as `service:run:default`;
- a pipeline (`runtime.run_as` in its YAML) or a scheduled tool job (`run_as` in
  its arguments) may name its own identity, `service:run:<name>`. It replaces
  the stand-ins those runs used to carry (`service:scheduler`, `system_cli`,
  `anonymous`...), never a person: a pipeline a person launches still acts as
  that person where it did.

Enterprise puts `service:run:default` in the group "Ejecuciones internas",
which starts with administration of the company: nothing that ran before stops
running. An administrator narrows that group, or gives a pipeline its own
identity with less, when they choose. The stand-ins keep what they had (the
group Todos) unless a run names an identity.

The identity travels as the call's `user_identifier`, so it survives the job
queue (a task stores it). The `service:run:` prefix cannot come from an API
key: a key's own identity is `service:<name>` with the name reduced to letters,
digits, dots and dashes. Without groups (core alone) nothing is checked.
"""

from __future__ import annotations

import re

SERVICE_PREFIX = "service:"
RUN_PREFIX = f"{SERVICE_PREFIX}run:"
DEFAULT_RUN_PRINCIPAL = f"{RUN_PREFIX}default"

#: Identities internal runs carried before R7 that are not a person.
STAND_INS = frozenset({"anonymous", "system_cli", "pipeline_backfill_trigger_api"})


def principal_for(name) -> str | None:
    """`service:run:<slug>` for a name an administrator wrote; None when empty.
    A value that already carries the prefix is normalized, not prefixed twice."""
    if not isinstance(name, str):
        return None
    text = name.strip().lower()
    if text.startswith(RUN_PREFIX):
        text = text[len(RUN_PREFIX):]
    slug = re.sub(r"[^a-z0-9._-]+", "-", text).strip("-")
    return f"{RUN_PREFIX}{slug}" if slug else None


def is_run_principal(value) -> bool:
    return isinstance(value, str) and value.startswith(RUN_PREFIX)


def is_person(value) -> bool:
    """A person's identifier: not empty, not a service identity, not a stand-in."""
    text = str(value or "").strip()
    return bool(text) and not text.lower().startswith(SERVICE_PREFIX) and text.lower() not in STAND_INS


def acting_identity(user_identifier, run_as) -> str | None:
    """Who a run acts as: a person stays themselves; otherwise the identity the run
    names (`run_as`), if any; otherwise what it carried before."""
    if is_person(user_identifier):
        return str(user_identifier).strip()
    return principal_for(run_as) or (str(user_identifier).strip() if user_identifier else None)


def effective(user_identifier) -> str:
    """Who a tool call is checked as: its identity, or the default when it has none."""
    return str(user_identifier or "").strip() or DEFAULT_RUN_PRINCIPAL
