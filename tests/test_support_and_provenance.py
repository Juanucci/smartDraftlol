"""Certeza (`Support`) y procedencia (`Provenance`) — v1.6.1.

Estos dos ejes existen para separar tres cosas que antes se apretaban en
`Polarity`: hacia dónde se inclina una interacción, bajo qué condición se
sostiene, y cuánta certeza hay sobre esa inclinación. El síntoma que los
motivó: en el hito 1.6, casi la mitad de las entradas de la vista causal
aportaban cero al score porque la única forma de expresar "esto es real
pero condicionado" era refugiarse en `CONDITIONAL`.
"""

from __future__ import annotations

from lol_reasoner.domain.enums import (
    ALL_PHASES,
    ConditionKind,
    Factor,
    Phase,
    Polarity,
    Provenance,
    Support,
)
from lol_reasoner.domain.query import MatchupQuery
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.trace import ReasoningTrace, TraceEntry
from lol_reasoner.recommend import recommend
from lol_reasoner.scoring.confidence import compute_confidence
from lol_reasoner.scoring.global_score import global_score, signed_contribution
from lol_reasoner.scoring.weights import DEFAULT_WEIGHTS


def _entry(**kwargs) -> TraceEntry:
    base = dict(
        id="x",
        rule_id="RX",
        rule_summary="s",
        category="c",
        phase=Phase.EARLY_LANE,
        factor=Factor.MECHANICAL_INTERACTION,
        polarity=Polarity.PRO,
        delta=0.2,
        premises=(),
        subject="x",
        text="t",
    )
    base.update(kwargs)
    return TraceEntry(**base)


def test_conditioned_pro_moves_the_score_but_less_than_a_structural_one():
    """El requisito central del punto 2 del brief: una ventaja
    condicionada PUEDE inclinar el score, sin volverse certeza."""

    structural = signed_contribution(_entry(support=Support.STRUCTURAL), DEFAULT_WEIGHTS)
    conditioned = signed_contribution(_entry(support=Support.CONDITIONED), DEFAULT_WEIGHTS)
    ambiguous = signed_contribution(_entry(support=Support.AMBIGUOUS), DEFAULT_WEIGHTS)

    assert conditioned > 0, "una ventaja condicionada no puede aportar cero"
    assert conditioned < structural, "tampoco puede pesar como una certeza estructural"
    assert conditioned < structural / 2, "y no debería llegar ni a media ventaja estructural"
    assert ambiguous == 0.0


def test_conditioned_pro_entry_also_raises_volatility():
    """Y el otro medio requisito: esa misma entrada PRO condicionada debe
    aumentar la volatilidad, no solo mover el score. Antes las condiciones
    colgadas de un PRO/CONTRA se descartaban por no ser `CONDITIONAL`."""

    mirror = ReasoningTrace(candidate_id="y", enemy_id="x")

    plain = ReasoningTrace(candidate_id="x", enemy_id="y")
    plain.add(_entry(id="a", support=Support.STRUCTURAL, causal_key="k1"))

    conditioned = ReasoningTrace(candidate_id="x", enemy_id="y")
    conditioned.add(
        _entry(
            id="a",
            support=Support.CONDITIONED,
            condition="depende de que el intercambio se extienda",
            condition_kind=ConditionKind.STRATEGIC,
            causal_key="k1",
        )
    )

    assert compute_confidence(plain, mirror).strategic_condition_count == 0
    result = compute_confidence(conditioned, mirror)
    assert result.strategic_condition_count == 1
    assert conditioned.entries[0].polarity == Polarity.PRO, "la condición viaja en una entrada PRO, no CONDITIONAL"


def test_ambiguous_support_never_moves_the_score_but_stays_in_the_explanation(champions):
    """`AMBIGUOUS` aporta cero, pero la observación se conserva entera:
    que el motor no pueda inclinarse no es motivo para ocultar el hecho."""

    trace = RuleEngine().build_trace(champions["darius"], champions["mordekaiser"], ALL_PHASES)
    ambiguous = [e for e in trace.entries if e.support == Support.AMBIGUOUS]
    assert ambiguous, "el par evaluado debe tener observaciones genuinamente ambiguas"

    for e in ambiguous:
        assert signed_contribution(e, DEFAULT_WEIGHTS) == 0.0
        assert e.polarity == Polarity.CONDITIONAL, "una entrada ambigua no puede afirmar dirección"
        assert e.text, "pero debe seguir explicándose"


def test_condition_kind_is_independent_of_polarity(champions):
    """`ConditionKind` clasifica el TIPO de incertidumbre; `Polarity` la
    dirección. Son ejes ortogonales: deben poder combinarse libremente."""

    engine = RuleEngine()
    combos = set()
    for cand, enemy in (("darius", "mordekaiser"), ("mordekaiser", "darius")):
        trace = engine.build_trace(champions[cand], champions[enemy], ALL_PHASES)
        for e in trace.entries:
            if e.condition_kind:
                combos.add((e.polarity, e.condition_kind))

    directional = {p for p, _k in combos if p != Polarity.CONDITIONAL}
    assert directional, "debe existir al menos una entrada PRO/CONTRA con condition_kind"
    kinds_on_directional = {k for p, k in combos if p != Polarity.CONDITIONAL}
    assert ConditionKind.STRATEGIC in kinds_on_directional or ConditionKind.EXECUTION in kinds_on_directional


def test_editorial_priors_are_labelled_as_manual_valuations(champions):
    rs = recommend(MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",)), champions)
    editorial = [e for e in rs.recommendations["darius"].trace_entries if e["provenance"] == "editorial_prior"]
    assert editorial, "los ejes escritos a mano deben seguir declarándose"
    for entry in editorial:
        assert "editorial" in entry["text"] or "valoración manual" in entry["text"], (
            "un prior editorial no puede presentarse como conclusión derivada del kit"
        )


def test_editorial_contribution_is_exactly_zero(champions):
    """En el hito 1.6 los priors editoriales aportaban el 40-64 % del
    movimiento de score. La primera versión de v1.6.1 los bajó a un peso
    reducido, pero seguían siendo decisivos: el veredicto se invertía al
    quitarlos. Ahora aportan CERO — se muestran, no deciden."""

    engine = RuleEngine()
    for cand, enemy in (("darius", "mordekaiser"), ("mordekaiser", "darius")):
        trace = engine.build_trace(champions[cand], champions[enemy], ALL_PHASES)
        causal = trace.deduped_for_scoring(cand)
        total = sum(abs(signed_contribution(e, DEFAULT_WEIGHTS)) for e in causal)
        editorial = sum(
            abs(signed_contribution(e, DEFAULT_WEIGHTS))
            for e in causal
            if e.provenance == Provenance.EDITORIAL_PRIOR
        )
        assert total > 0
        assert editorial == 0.0, f"{cand}: un prior editorial está moviendo el score mecánico"


def test_editorial_prior_does_not_multiply_across_phases(champions):
    """Un prior no puede pesar más solo por reaparecer en varias fases."""

    trace = RuleEngine().build_trace(champions["darius"], champions["mordekaiser"], ALL_PHASES)
    causal = trace.deduped_for_scoring("darius")
    keys = [e.causal_key for e in causal if e.provenance == Provenance.EDITORIAL_PRIOR]
    assert len(keys) == len(set(keys)), "cada prior editorial debe contribuir una sola vez"
    assert all(k is not None for k in keys), "un prior sin causal_key se contaría por fase"


def test_support_multipliers_are_configurable_and_visible_in_the_trace(champions):
    """El multiplicador debe vivir en config y viajar en la traza: si no
    es auditable entrada por entrada, es un número mágico."""

    assert set(DEFAULT_WEIGHTS.support_weights) == set(Support)
    assert set(DEFAULT_WEIGHTS.provenance_weights) == set(Provenance)

    rs = recommend(MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",)), champions)
    for entry in rs.recommendations["darius"].trace_entries:
        assert entry["support"] in {s.value for s in Support}
        assert entry["provenance"] in {p.value for p in Provenance}


def test_changing_the_conditioned_multiplier_changes_the_score(champions):
    """Prueba de que el multiplicador es realmente configurable y no está
    incrustado en las reglas."""

    import dataclasses

    trace = RuleEngine().build_trace(champions["darius"], champions["mordekaiser"], ALL_PHASES)
    base = global_score(trace, DEFAULT_WEIGHTS, subject_id="darius")[0]

    tweaked = dataclasses.replace(
        DEFAULT_WEIGHTS,
        support_weights={**DEFAULT_WEIGHTS.support_weights, Support.CONDITIONED: 0.9},
    )
    assert global_score(trace, tweaked, subject_id="darius")[0] != base
