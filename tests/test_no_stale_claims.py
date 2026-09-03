"""Hito 1.5, punto 17: no debe sobrevivir ninguna cadena que afirme que
el daño verdadero ignora escudos, o que un escudo revierte cargas de
acumulación — las dos afirmaciones falsas que motivaron eliminar S01/S02
del hito 1. Se escanea tanto el KB crudo como la traza generada."""

from __future__ import annotations

from importlib import resources

from lol_reasoner.domain.enums import ALL_PHASES
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.rules.specific import SPECIFIC_INTERACTIONS

_FORBIDDEN_FRAGMENTS = (
    "ignora escudos",
    "ignora el escudo",
    "atraviesa escudos",
    "atraviesa el escudo",
    "no lo mitiga",
    "no es mitigado por",
    "revierte cargas",
    "elimina cargas",
    "quita cargas",
    "resetea las cargas",
)


def _all_yaml_text() -> str:
    parts = []
    for name in ("darius.yaml", "mordekaiser.yaml"):
        path = resources.files("lol_reasoner.knowledge.champions").joinpath(name)
        with resources.as_file(path) as p:
            parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts).lower()


def test_specific_interactions_are_empty():
    """S01 y S02 (hito 1) resultaron ser afirmaciones falsas. Que el
    modelo estructural las haya absorbido sin necesitar ninguna
    excepción es, en sí, la validación del hito."""

    assert SPECIFIC_INTERACTIONS == ()


_NEGATIONS = (" no ", " ni ", " nunca ", " tampoco ")


def _contains_unnegated_claim(haystack: str, fragment: str) -> bool:
    """True si `fragment` aparece en `haystack` sin una negación inmediatamente
    antes (para no confundir la afirmación falsa "revierte cargas" con la
    aclaración correcta "no elimina ni revierte cargas")."""

    start = 0
    while True:
        idx = haystack.find(fragment, start)
        if idx == -1:
            return False
        window = haystack[max(0, idx - 20) : idx]
        if not any(neg in window for neg in _NEGATIONS):
            return True
        start = idx + 1


def test_kb_yaml_text_has_no_forbidden_claims():
    text = _all_yaml_text()
    for fragment in _FORBIDDEN_FRAGMENTS:
        assert not _contains_unnegated_claim(text, fragment), f"el YAML todavía contiene la afirmación obsoleta: '{fragment}'"


def test_trace_text_has_no_forbidden_claims(darius, mordekaiser):
    engine = RuleEngine()
    trace_d = engine.build_trace(darius, mordekaiser, ALL_PHASES)
    trace_m = engine.build_trace(mordekaiser, darius, ALL_PHASES)
    for trace in (trace_d, trace_m):
        for entry in trace.entries:
            haystack = " ".join(filter(None, [entry.text, entry.condition, entry.invalidated_if])).lower()
            for fragment in _FORBIDDEN_FRAGMENTS:
                assert not _contains_unnegated_claim(haystack, fragment), f"{entry.id} contiene la afirmación obsoleta: '{fragment}'"
