# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
import os

from injector import inject, singleton

from iatoolkit.common.exceptions import IAToolkitException


@singleton
class OperatorIdentityService:
    """Who operates this deployment, and who collects from it — two questions.

    They were one, answered by one name, and that held only because on our own
    deployment the answers coincide. They came apart the first time a customer ran
    IAToolkit on its own infrastructure: that installation *is* operated by its
    company — its accounts live there, its console belongs to it — and it collects
    from nobody. The monthly close refused to run because it asked for a merchant
    account that had no reason to exist.

    So:

    * **The operator** is identity. Where this deployment's own accounts live,
      which company you must be signed into to reach the control center, and which
      company the console leaves out of its own portfolio. Every installation has
      one.
    * **The billing company** is money. Whose merchant account charges a card,
      whose bank details sign a transfer notice, whose Stripe configuration holds
      the webhook secret. Only an installation that collects has one, and it
      defaults to the operator because usually they are the same company — but not
      always: the company that runs the deployment and the entity that issues the
      invoices can be in different countries.

    Lives in the core because the core, Enterprise and the website all ask it, and
    a rule restated in three repositories drifts. Same reason ``ServiceModel`` is
    here.
    """

    #: Identity. Read on every request that reaches the console.
    SETTING_NAME = "IAT_OPERATOR_COMPANY"

    #: Money. Optional: absent means "the operator collects", which is the common
    #: case. Named separately so an installation that collects for a different
    #: legal entity can say so, and so one that collects for nobody can leave it
    #: empty instead of inventing a merchant.
    BILLING_SETTING_NAME = "IAT_BILLING_COMPANY_SHORT_NAME"

    #: Held on the class, not the instance. Callers that have a repository at hand
    #: build their own instance rather than asking the injector, so an instance
    #: cache resolved — and logged, and queried the database — once per request
    #: instead of once per process.
    _resolved: str | None = None

    @classmethod
    def reset_cache(cls) -> None:
        """Forget the resolved name. For tests: it cannot change at runtime."""
        OperatorIdentityService._resolved = None

    @classmethod
    def stated_name(cls) -> str:
        """The operator, as this deployment names it. Empty when nothing names it.

        For callers with no database at hand — and there is nothing to verify: an
        explicitly configured name was never checked against the database, and a
        company that does not exist cannot authenticate anyone.

        Empty rather than a guess. The name of another deployment travelling into
        this one is what made a monthly close resolve the payment configuration of
        a company that was not there and mark every invoice failed.
        """
        return (os.getenv(cls.SETTING_NAME) or "").strip().lower()

    @classmethod
    def stated_billing_name(cls) -> str:
        """Who collects, as this deployment names it. Empty when nobody does."""
        explicit = (os.getenv(cls.BILLING_SETTING_NAME) or "").strip().lower()
        return explicit or cls.stated_name()

    @inject
    def __init__(self):
        # No database: since the legacy fallback went away there is nothing to
        # verify. The answers are two environment variables and a cache.
        pass

    def company_short_name(self) -> str:
        """The operator company, resolved once per process.

        Cached because the answer cannot change without a deployment, and this is
        read on paths that run per request.
        """
        if OperatorIdentityService._resolved:
            return OperatorIdentityService._resolved

        configured = self.stated_name()
        if configured:
            OperatorIdentityService._resolved = configured
            logging.info("Operator company: '%s' (from %s).", configured, self.SETTING_NAME)
            return configured

        # Deliberately loud, and about identity rather than money: without this
        # name nobody can be signed in as the operator and the console has no
        # portfolio to show.
        raise IAToolkitException(
            IAToolkitException.ErrorType.CONFIG_ERROR,
            f"This deployment does not say who operates it. Set {self.SETTING_NAME} "
            f"to the short name of the company that runs it.",
        )

    def billing_company_short_name(self) -> str:
        """The company whose merchant account collects.

        Falls back to the operator, because usually they are the same company.
        Asked for only where money moves — a card being charged, a transfer notice
        being signed, a webhook secret being read — so an installation that
        collects from nobody never has to answer it.
        """
        explicit = (os.getenv(self.BILLING_SETTING_NAME) or "").strip().lower()
        if explicit:
            return explicit

        try:
            return self.company_short_name()
        except IAToolkitException:
            # The message has to be about collecting, because that is what the
            # caller was doing. Pointing at the operator setting here sends
            # somebody to configure identity for a payment problem.
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                f"This deployment has no company to collect with. Set "
                f"{self.BILLING_SETTING_NAME} to the company whose merchant "
                f"account charges, or {self.SETTING_NAME} if the operator collects.",
            )
