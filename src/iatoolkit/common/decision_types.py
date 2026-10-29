# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""Types of a decision model call (BL-008).

A decision model does not write text: it answers a fixed set of questions about
a case (the `state`) with calibrated probabilities. The contract is the one
OpenRouter serves at `/api/alpha/decisions` for every decision model, and it is
copied here as is, without a translation layer: questions travel as a map
`{name: question}`, and each answer comes back under the same name.

Only three question types are supported: `noul` (yes/no), `choice` (one of a set
of options) and `score` (an ordered scale). The API also has `box`, a bounding
box over an image, which needs `assets` and is out of the first stage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

QUESTION_NOUL = "noul"
QUESTION_CHOICE = "choice"
QUESTION_SCORE = "score"
QUESTION_TYPES = (QUESTION_NOUL, QUESTION_CHOICE, QUESTION_SCORE)

# Same shape as a tool argument name: the answers come back keyed by it, and the
# agent's structured output exposes them under it.
_QUESTION_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_QUESTIONS = 20


DECISION_MODEL_KIND = "decision"


def model_kind(model_config: dict | None) -> str:
    """The kind of model a configuration describes: "decision", or "" for chat.

    Comes from the catalogue (`capabilities.kind`, written by `models-sync`); a
    company.yaml entry outside the catalogue may state it at the top level.
    """
    if not isinstance(model_config, dict):
        return ""
    capabilities = model_config.get("capabilities")
    kind = capabilities.get("kind") if isinstance(capabilities, dict) else None
    return str(kind or model_config.get("kind") or "").strip().lower()


def is_decision_model(model_config: dict | None) -> bool:
    return model_kind(model_config) == DECISION_MODEL_KIND


def chat_models(models: list | None) -> list:
    """The models that write text: everything but decision models.

    A company enables decision models like any other, so they are in its list
    of models; but they cannot hold a conversation, so every place that picks a
    model to chat with (the chat selector, the default, system agents) skips them.
    """
    return [model for model in models or [] if not (isinstance(model, dict) and is_decision_model(model))]


class DecisionSpecError(ValueError):
    """A decision spec that cannot be sent: the message names the field."""


@dataclass(frozen=True)
class DecisionQuestion:
    name: str
    type: str
    instructions: str
    #: `noul`: optional {"true": ..., "false": ...}; `choice`: {option: description};
    #: `score`: list of level descriptions, index 0 first.
    criteria: dict[str, str] | list[str] | None = None

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type, "instructions": self.instructions}
        if self.criteria:
            payload["criteria"] = self.criteria
        return payload


def _clean_text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def parse_question(name: str, raw: Any) -> DecisionQuestion:
    if not isinstance(name, str) or not _QUESTION_NAME_RE.match(name):
        raise DecisionSpecError(
            f"Question name '{name}' is invalid: use letters, digits and '_', starting with a letter."
        )
    if not isinstance(raw, dict):
        raise DecisionSpecError(f"Question '{name}' must be an object.")

    question_type = _clean_text(raw.get("type")).lower()
    if question_type not in QUESTION_TYPES:
        raise DecisionSpecError(
            f"Question '{name}' has type '{question_type}'; expected one of {', '.join(QUESTION_TYPES)}."
        )

    instructions = _clean_text(raw.get("instructions"))
    if not instructions:
        raise DecisionSpecError(f"Question '{name}' needs 'instructions'.")

    raw_criteria = raw.get("criteria")
    criteria: dict[str, str] | list[str] | None = None

    if question_type == QUESTION_NOUL:
        if raw_criteria not in (None, {}, ""):
            if not isinstance(raw_criteria, dict):
                raise DecisionSpecError(f"Question '{name}': 'criteria' of a noul is {{true, false}}.")
            unknown = set(str(key).lower() for key in raw_criteria) - {"true", "false"}
            if unknown:
                raise DecisionSpecError(
                    f"Question '{name}': noul criteria only accept 'true' and 'false'."
                )
            criteria = {
                str(key).lower(): _clean_text(value)
                for key, value in raw_criteria.items()
                if _clean_text(value)
            } or None

    elif question_type == QUESTION_CHOICE:
        if not isinstance(raw_criteria, dict) or len(raw_criteria) < 2:
            raise DecisionSpecError(
                f"Question '{name}': a choice needs 'criteria' with at least two options."
            )
        criteria = {}
        for option, description in raw_criteria.items():
            option_name = _clean_text(option)
            option_description = _clean_text(description)
            if not option_name:
                raise DecisionSpecError(f"Question '{name}': an option has no name.")
            if not option_description:
                raise DecisionSpecError(f"Question '{name}': option '{option_name}' needs a description.")
            criteria[option_name] = option_description

    else:  # score
        if not isinstance(raw_criteria, list) or len(raw_criteria) < 2:
            raise DecisionSpecError(
                f"Question '{name}': a score needs 'criteria' as a list of at least two levels."
            )
        criteria = [_clean_text(level) for level in raw_criteria]
        if any(not level for level in criteria):
            raise DecisionSpecError(f"Question '{name}': every score level needs a description.")

    return DecisionQuestion(name=name, type=question_type, instructions=instructions, criteria=criteria)


def parse_decision_spec(spec: Any) -> dict[str, DecisionQuestion]:
    """The questions of a decision spec, validated; raises DecisionSpecError.

    The spec is `{"questions": {name: question}}`. It is validated in code before
    any call because the API answers a bad question with a 400 that only names
    the field path, after a network round trip.
    """
    if not isinstance(spec, dict):
        raise DecisionSpecError("The decision spec must be an object with 'questions'.")
    raw_questions = spec.get("questions")
    if not isinstance(raw_questions, dict) or not raw_questions:
        raise DecisionSpecError("The decision spec needs at least one question.")
    if len(raw_questions) > MAX_QUESTIONS:
        raise DecisionSpecError(f"A decision spec accepts at most {MAX_QUESTIONS} questions.")
    return {name: parse_question(name, raw) for name, raw in raw_questions.items()}


def normalize_decision_spec(spec: Any) -> dict[str, Any]:
    """The spec as it is stored: validated questions, in their order."""
    questions = parse_decision_spec(spec)
    return {"questions": {name: question.to_wire() for name, question in questions.items()}}


@dataclass(frozen=True)
class DecisionAnswer:
    name: str
    type: str
    #: The answer itself: `True`/`False` for noul, the option for choice, the
    #: weighted average (0-based) for score.
    value: Any
    confidence: float | None
    probabilities: dict[str, float] = field(default_factory=dict)
    legend: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.type,
            "value": self.value,
            "confidence": self.confidence,
            "probabilities": dict(self.probabilities),
        }
        if self.legend:
            payload["legend"] = dict(self.legend)
        return payload


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_answer(name: str, raw: Any) -> DecisionAnswer:
    raw = raw if isinstance(raw, dict) else {}
    answer_type = _clean_text(raw.get("type")).lower()
    probabilities = {
        str(key): float(value)
        for key, value in (raw.get("probabilities") or {}).items()
        if _as_float(value) is not None
    }

    if answer_type == QUESTION_NOUL:
        # A noul answer carries only p(true); its confidence is not in the
        # response, so it is derived the same way for every model: how far p
        # is from a coin toss.
        p_true = _as_float(raw.get("noul"))
        if p_true is None:
            return DecisionAnswer(name=name, type=answer_type, value=None, confidence=None)
        return DecisionAnswer(
            name=name,
            type=answer_type,
            value=p_true >= 0.5,
            confidence=round(abs(2 * p_true - 1), 6),
            probabilities={"true": p_true, "false": round(1 - p_true, 6)},
        )

    if answer_type == QUESTION_SCORE:
        legend = {str(key): _clean_text(value) for key, value in (raw.get("legend") or {}).items()}
        return DecisionAnswer(
            name=name,
            type=answer_type,
            value=_as_float(raw.get("score")),
            confidence=_as_float(raw.get("confidence")),
            probabilities=probabilities,
            legend=legend,
        )

    return DecisionAnswer(
        name=name,
        type=answer_type or QUESTION_CHOICE,
        value=raw.get("choice"),
        confidence=_as_float(raw.get("confidence")),
        probabilities=probabilities,
    )


@dataclass(frozen=True)
class DecisionResult:
    answers: dict[str, DecisionAnswer]
    #: The dated model that answered (`typesafe/jev-1.14-20261014`), not the key asked for.
    model: str
    provider: str | None
    response_id: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    latency_ms: int

    @classmethod
    def from_response(cls, body: dict[str, Any], *, requested_model: str, latency_ms: int) -> "DecisionResult":
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        raw_answers = body.get("answers") if isinstance(body.get("answers"), dict) else {}
        return cls(
            answers={name: parse_answer(name, raw) for name, raw in raw_answers.items()},
            model=_clean_text(body.get("model")) or requested_model,
            provider=_clean_text(body.get("provider")) or None,
            response_id=_clean_text(body.get("id")) or None,
            input_tokens=int(_as_float(usage.get("input_tokens")) or 0),
            output_tokens=int(_as_float(usage.get("output_tokens")) or 0),
            cost_usd=_as_float(usage.get("cost")),
            latency_ms=int(latency_ms),
        )

    def answers_dict(self) -> dict[str, Any]:
        return {name: answer.to_dict() for name, answer in self.answers.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "answers": self.answers_dict(),
            "model": self.model,
            "provider": self.provider,
            "response_id": self.response_id,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": self.cost_usd,
            },
            "latency_ms": self.latency_ms,
        }

    def summary_text(self) -> str:
        """One line per question, for the places that show text (history, logs)."""
        lines = []
        for name, answer in self.answers.items():
            confidence = "" if answer.confidence is None else f" (confianza {answer.confidence:.2f})"
            if answer.type == QUESTION_NOUL:
                value = "sí" if answer.value else "no"
            elif answer.type == QUESTION_SCORE and answer.value is not None:
                value = f"{answer.value:.2f}"
            else:
                value = str(answer.value)
            lines.append(f"{name}: {value}{confidence}")
        return "\n".join(lines)
