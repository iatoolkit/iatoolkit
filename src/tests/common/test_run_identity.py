"""BL-034 R7: who a run without a person acts as."""

from iatoolkit.common import run_identity


def test_names_become_run_principals():
    assert run_identity.principal_for("Cobranza Diaria") == "service:run:cobranza-diaria"
    assert run_identity.principal_for("service:run:Cobranza") == "service:run:cobranza"
    assert run_identity.principal_for("  ") is None
    assert run_identity.principal_for(None) is None and run_identity.principal_for(3) is None


def test_a_named_identity_replaces_stand_ins_never_a_person():
    acting = run_identity.acting_identity
    assert acting("ana@acme.cl", "cobranza") == "ana@acme.cl"
    for stand_in in ("service:scheduler", "system_cli", "anonymous", "pipeline_backfill_trigger_api", None, ""):
        assert acting(stand_in, "cobranza") == "service:run:cobranza"
    # Without a named identity, what the run carried stays.
    assert acting("service:scheduler", None) == "service:scheduler"
    assert acting(None, None) is None


def test_a_call_without_identity_is_checked_as_the_default():
    assert run_identity.effective(None) == run_identity.DEFAULT_RUN_PRINCIPAL
    assert run_identity.effective("service:run:x") == "service:run:x"
