# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
import os

from injector import inject, singleton

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.profile_repo import ProfileRepo


@singleton
class OperatorIdentityService:
    """Which company operates this deployment.

    One question that four places used to answer with the same typed string: where
    the operator's own accounts live, which company you must be signed into to
    reach the control center, whose portfolio the console lists, and — the one that
    handles money — whose merchant account collects invoices.

    Lives in the core because the core, Enterprise and the website all ask it, and
    a rule restated in three repositories drifts. Same reason ``ServiceModel`` is
    here.
    """

    #: The name this deployment used before the question was a setting. Kept as a
    #: fallback so nothing has to be configured here, but only honoured when the
    #: company actually exists: on any other deployment the name is meaningless,
    #: and silently accepting it is what made a monthly close resolve the payment
    #: configuration of a company that was not there and mark every invoice failed.
    LEGACY_COMPANY_SHORT_NAME = "iat_store"

    #: In order. The second name predates this service and is honoured by the
    #: Stripe webhook, so a deployment that already set it keeps working without
    #: being asked to set a second variable for the same fact.
    SETTING_NAMES = ("IAT_OPERATOR_COMPANY", "IAT_BILLING_COMPANY_SHORT_NAME")
    SETTING_NAME = SETTING_NAMES[0]

    @classmethod
    def stated_name(cls) -> str:
        """What this deployment calls its operator, without checking it exists.

        For callers with no database at hand. The verification belongs on the
        money path — see ``company_short_name`` — and skipping it here is safe
        because those callers fail in the open: a company that does not exist
        cannot authenticate anyone and holds no payment configuration.
        """
        for setting in cls.SETTING_NAMES:
            value = (os.getenv(setting) or "").strip().lower()
            if value:
                return value
        return cls.LEGACY_COMPANY_SHORT_NAME

    @inject
    def __init__(self, profile_repo: ProfileRepo):
        self.profile_repo = profile_repo
        self._resolved: str | None = None

    def company_short_name(self) -> str:
        """The operator company, resolved once per process.

        Cached because the answer cannot change without a deployment, and this is
        read on paths that run per request and per invoice.
        """
        if self._resolved:
            return self._resolved

        for setting in self.SETTING_NAMES:
            configured = (os.getenv(setting) or "").strip().lower()
            if configured:
                self._resolved = configured
                logging.info("Operator company: '%s' (from %s).", configured, setting)
                return self._resolved

        if self._company_exists(self.LEGACY_COMPANY_SHORT_NAME):
            self._resolved = self.LEGACY_COMPANY_SHORT_NAME
            logging.info(
                "Operator company: '%s' (default). Set %s to name it explicitly.",
                self._resolved,
                self.SETTING_NAME,
            )
            return self._resolved

        # Deliberately loud. The alternative is what used to happen: a name from
        # another deployment travels down to the payment configuration and the
        # close writes failed invoices, which reads as a collection problem.
        raise IAToolkitException(
            IAToolkitException.ErrorType.CONFIG_ERROR,
            f"This deployment has no operator company. Set {self.SETTING_NAME} to the "
            f"short name of the company that operates it (there is no "
            f"'{self.LEGACY_COMPANY_SHORT_NAME}' company in this database).",
        )

    def _company_exists(self, short_name: str) -> bool:
        try:
            return self.profile_repo.get_company_by_short_name(short_name) is not None
        except Exception as exc:
            # Unreadable is not the same as absent, and guessing either way here is
            # worse than saying so: the caller gets the explicit error below.
            logging.warning("Could not check whether company '%s' exists: %s", short_name, exc)
            return False
