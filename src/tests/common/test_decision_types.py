import pytest

from iatoolkit.common.decision_types import (
    DecisionResult,
    DecisionSpecError,
    normalize_decision_spec,
    parse_decision_spec,
)

SPEC = {
    "questions": {
        "es_cobranza": {"type": "noul", "instructions": "¿Es un correo de cobranza?"},
        "area": {
            "type": "choice",
            "instructions": "¿Qué área debe atenderlo?",
            "criteria": {"cobranza": "Pagos y facturas.", "legal": "Reclamos formales."},
        },
        "urgencia": {
            "type": "score",
            "instructions": "¿Qué tan urgente es?",
            "criteria": ["Puede esperar", "Esta semana", "Hoy"],
        },
    }
}

# Recorded from /api/alpha/decisions (typesafe/jev-1.14), 2026-10-29.
RESPONSE = {
    "model": "typesafe/jev-1.14-20261014",
    "answers": {
        "es_cobranza": {"type": "noul", "noul": 0.99},
        "area": {
            "type": "choice",
            "choice": "cobranza",
            "probabilities": {"cobranza": 1, "legal": 0},
            "confidence": 1,
        },
        "urgencia": {
            "type": "score",
            "score": 1.58,
            "legend": {"0": "Puede esperar", "1": "Esta semana", "2": "Hoy"},
            "probabilities": {"0": 0, "1": 0.42, "2": 0.58},
            "confidence": 0.58,
        },
    },
    "usage": {"input_tokens": 567, "output_tokens": 90, "cost": 2.3814e-05},
    "id": "gen-dec-1",
    "provider": "TypeSafe",
}


class TestDecisionSpec:
    def test_parses_the_three_question_types_in_order(self):
        questions = parse_decision_spec(SPEC)
        assert list(questions) == ["es_cobranza", "area", "urgencia"]
        assert questions["es_cobranza"].criteria is None
        assert questions["area"].criteria == {"cobranza": "Pagos y facturas.", "legal": "Reclamos formales."}
        assert questions["urgencia"].criteria == ["Puede esperar", "Esta semana", "Hoy"]

    def test_normalize_returns_the_wire_shape(self):
        normalized = normalize_decision_spec(SPEC)
        assert normalized["questions"]["es_cobranza"] == {
            "type": "noul", "instructions": "¿Es un correo de cobranza?",
        }
        assert normalized["questions"]["urgencia"]["criteria"][0] == "Puede esperar"

    @pytest.mark.parametrize("spec, fragment", [
        (None, "object"),
        ({"questions": {}}, "at least one"),
        ({"questions": {"1x": {"type": "noul", "instructions": "?"}}}, "invalid"),
        ({"questions": {"q": {"type": "box", "instructions": "?"}}}, "expected one of"),
        ({"questions": {"q": {"type": "noul"}}}, "instructions"),
        ({"questions": {"q": {"type": "choice", "instructions": "?", "criteria": {"a": "x"}}}}, "two options"),
        ({"questions": {"q": {"type": "choice", "instructions": "?", "criteria": {"a": "x", "b": ""}}}}, "description"),
        ({"questions": {"q": {"type": "score", "instructions": "?", "criteria": {"a": "x"}}}}, "list"),
        ({"questions": {"q": {"type": "noul", "instructions": "?", "criteria": {"maybe": "x"}}}}, "true"),
    ])
    def test_rejects_invalid_specs(self, spec, fragment):
        with pytest.raises(DecisionSpecError) as exc:
            parse_decision_spec(spec)
        assert fragment in str(exc.value)


class TestDecisionResult:
    def test_parses_a_recorded_response(self):
        result = DecisionResult.from_response(RESPONSE, requested_model="typesafe/jev-1.14", latency_ms=861)

        assert result.model == "typesafe/jev-1.14-20261014"
        assert result.provider == "TypeSafe"
        assert result.input_tokens == 567 and result.output_tokens == 90
        assert result.cost_usd == pytest.approx(2.3814e-05)

        noul = result.answers["es_cobranza"]
        assert noul.value is True
        # The API sends no confidence for noul: it is |2p - 1|.
        assert noul.confidence == pytest.approx(0.98)
        assert noul.probabilities == {"true": 0.99, "false": pytest.approx(0.01)}

        assert result.answers["area"].value == "cobranza"
        assert result.answers["urgencia"].value == pytest.approx(1.58)
        assert result.answers["urgencia"].legend["2"] == "Hoy"

    def test_summary_text_has_one_line_per_question(self):
        result = DecisionResult.from_response(RESPONSE, requested_model="m", latency_ms=1)
        assert result.summary_text().splitlines() == [
            "es_cobranza: sí (confianza 0.98)",
            "area: cobranza (confianza 1.00)",
            "urgencia: 1.58 (confianza 0.58)",
        ]
