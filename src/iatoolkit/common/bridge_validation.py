# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# Shared validation for the `bridge_id` that SQL sources and HTTP tools point
# at. Lives here rather than in either service because both reference the same
# registry and must reject the same way — a check that drifts between the two
# is worse than no check, since the GUI would accept in one screen what it
# refuses in the other.

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.bridge_repo import BridgeRepo
from iatoolkit.repositories.models import Company


def validate_bridge_is_registered(bridge_repo: BridgeRepo, company: Company, bridge_id: str) -> None:
    """
    Rejects a bridge_id with no registered bridge behind it.

    Worth the extra check because the failure it prevents is genuinely
    confusing: an unregistered bridge_id used to surface only at runtime, as
    "Bridge '<id>' is not connected" — the exact same message as a bridge that
    is simply down. Catching it at save time separates "you typed it wrong"
    from "your agent is offline".

    Skipped entirely for companies that have no bridges registered yet: those
    still reference bridges by API key name (the pre-registry rule), and
    refusing to save would break configurations that work today. The check
    turns itself on once the company is backfilled.
    """
    registered = bridge_repo.get_by_company(company)
    if not registered:
        return

    if not any(b.bridge_id == bridge_id for b in registered):
        known = ", ".join(sorted(b.bridge_id for b in registered))
        raise IAToolkitException(
            IAToolkitException.ErrorType.INVALID_PARAMETER,
            f"Unknown bridge_id '{bridge_id}'. Registered bridges for this company: {known}",
        )
