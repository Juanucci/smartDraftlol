"""Deduplicación causal y guardrails de complejidad — v1.6.1.

La auditoría de v1.6.1 encontró que 9 de 20 construcciones de
`RuleEffect` no traían `causal_key`, y que eso producía doble conteo
real: la comparación de recompensas de acumulación aportaba tres veces
(una por fase disponible) y era el 100 % de su factor; la regla de
sustain aportaba dos. Además, las contradicciones de Confidence se
calculaban sobre la traza cruda, así que una misma tensión repetida en
tres fases contaba como tres contradicciones distintas.
"""

from __future__ import annotations

import ast
import inspect

from lol_reasoner.domain.enums import ALL_PHASES, Polarity
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.rules import general, stacking
from lol_reasoner.reasoning.rules.registry import (
    ALL_GENERAL_RULES,
    MAX_CATEGORIES_PER_RULE,
    MAX_GENERAL_RULES,
)
from lol_reasoner.scoring.confidence import compute_confidence
from lol_reasoner.scoring.global_score import signed_contribution
from lol_reasoner.scoring.weights import DEFAULT_WEIGHTS


def _traces(champions):
    engine = RuleEngine()
    return (
        ("darius", engine.build_trace(champions["darius"], champions["mordekaiser"], ALL_PHASES)),
        ("mordekaiser", engine.build_trace(champions["mordekaiser"], champions["darius"], ALL_PHASES)),
    )


def test_no_causal_key_contributes_more_than_once(champions):
    for subject, trace in _traces(champions):
        keys = [e.causal_key for e in trace.deduped_for_scoring(subject) if e.causal_key]
        assert len(keys) == len(set(keys)), f"{subject}: una causa aporta más de una vez al score"


def test_repeated_causes_survive_in_the_raw_trace_for_audit(champions):
    """La dedup es de CÁLCULO, no de registro: la traza cruda conserva
    todas las apariciones para poder auditar en qué fases sigue vigente
    un hecho."""

    for subject, trace in _traces(champions):
        raw_keys = [e.causal_key for e in trace.entries if e.causal_key]
        deduped_keys = [e.causal_key for e in trace.deduped_for_scoring(subject) if e.causal_key]
        assert len(raw_keys) > len(deduped_keys), f"{subject}: la traza cruda debería conservar repeticiones"


def test_every_scoring_rule_effect_declares_a_causal_key():
    """Guardrail AST: toda construcción de `RuleEffect` que pueda puntuar
    (polaridad PRO/CONTRA, o una variable de polaridad) debe traer
    `causal_key`. Sin esto, un descuido vuelve a producir doble conteo y
    nada falla."""

    offenders: list[str] = []
    for module in (general, stacking):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "RuleEffect"):
                continue
            kwargs = {k.arg for k in node.keywords}
            polarity = next((ast.unparse(k.value) for k in node.keywords if k.arg == "polarity"), "")
            can_score = polarity != "Polarity.CONDITIONAL"
            if can_score and "causal_key" not in kwargs:
                offenders.append(f"{module.__name__}:{node.lineno}")
    assert not offenders, f"RuleEffect que puede puntuar sin causal_key: {offenders}"


def test_shared_observations_without_score_also_declare_a_causal_key():
    """Las observaciones sin score que representan un hecho compartido
    deduplicable también necesitan clave: si no, inflan condiciones y
    contradicciones al repetirse por fase."""

    missing: list[str] = []
    for module in (general, stacking):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "RuleEffect"):
                continue
            kwargs = {k.arg for k in node.keywords}
            if "causal_key" not in kwargs:
                missing.append(f"{module.__name__}:{node.lineno}")
    assert not missing, (
        "toda entrada debe declarar causal_key en v1.6.1 (las sin score también, "
        f"para no inflar condiciones al repetirse por fase): {missing}"
    )


def test_contradictions_are_counted_on_the_causal_view(champions):
    """Una misma tensión repetida en tres fases es UNA contradicción."""

    engine = RuleEngine()
    trace = engine.build_trace(champions["darius"], champions["mordekaiser"], ALL_PHASES)
    mirror = engine.build_trace(champions["mordekaiser"], champions["darius"], ALL_PHASES)
    result = compute_confidence(trace, mirror)

    from collections import defaultdict

    pos, neg = defaultdict(float), defaultdict(float)
    for e in trace.entries:  # vista CRUDA, la que se usaba antes
        key = (e.phase, e.factor)
        if e.polarity == Polarity.PRO:
            pos[key] += e.delta
        elif e.polarity == Polarity.CONTRA:
            neg[key] += e.delta
    raw_count = sum(
        1
        for k in set(pos) | set(neg)
        if pos.get(k, 0) > 0 and neg.get(k, 0) > 0 and min(pos[k], neg[k]) / max(pos[k], neg[k]) >= 0.4
    )
    assert result.contradiction_count <= raw_count


def test_narrator_and_score_read_the_same_causal_view(champions):
    """La explicación no puede listar como razón algo que el score no
    contó, ni al revés."""

    from lol_reasoner.explain.narrator import build_reasons, build_risks

    for subject, trace in _traces(champions):
        causal_ids = {e.id for e in trace.deduped_for_scoring(subject)}
        for item in (
            *build_reasons(trace, subject_id=subject, weights=DEFAULT_WEIGHTS),
            *build_risks(trace, subject_id=subject, weights=DEFAULT_WEIGHTS),
        ):
            assert item.entry_id in causal_ids


def test_phase_notes_separate_raw_from_effective(champions):
    """Las dos vistas deben coexistir etiquetadas: el conteo crudo es
    auditoría, las contribuciones efectivas son lo que movió el score."""

    from lol_reasoner.explain.narrator import build_phase_notes

    for subject, trace in _traces(champions):
        notes = build_phase_notes(trace, subject_id=subject, weights=DEFAULT_WEIGHTS)
        total_effective = sum(
            sum(n.effective_contributions_by_factor.values()) for n in notes.values()
        )
        expected = sum(signed_contribution(e, DEFAULT_WEIGHTS) for e in trace.deduped_for_scoring(subject))
        assert abs(total_effective - expected) < 1e-3, f"{subject}: las contribuciones efectivas no cierran con el score"
        assert all(n.raw_entry_count >= 0 for n in notes.values())


# ------------------------------------------------------------- complejidad


def test_no_rule_accumulates_too_many_categories():
    """El guardrail que de verdad detecta un monolito. La ex-G03 declaraba
    cinco categorías (daño verdadero, penetración, dos de escudo y daño a
    objetivo único) y escondía tres escaneos unidireccionales."""

    offenders = {r.id: sorted(r.categories) for r in ALL_GENERAL_RULES if len(r.categories) > MAX_CATEGORIES_PER_RULE}
    assert not offenders, f"reglas con demasiadas responsabilidades: {offenders}"


def test_rule_count_guardrail_is_soft_but_checked():
    assert len(ALL_GENERAL_RULES) <= MAX_GENERAL_RULES, (
        f"{len(ALL_GENERAL_RULES)} reglas generales supera el tope blando de {MAX_GENERAL_RULES}. "
        "No es motivo para fusionar conceptos distintos: revisar si alguna sobra."
    )


def test_registry_does_not_assert_at_import_time():
    """El tope de reglas no debe volver a ser un `assert` en import time:
    fue exactamente eso lo que empujó a fusionar dos conceptos distintos
    en una sola regla en el hito 1.6."""

    from lol_reasoner.reasoning.rules import registry

    source = inspect.getsource(registry)
    tree = ast.parse(source)
    top_level_asserts = [n for n in tree.body if isinstance(n, ast.Assert)]
    assert not top_level_asserts, "el guardrail de cantidad debe verificarse en tests, no en import time"
