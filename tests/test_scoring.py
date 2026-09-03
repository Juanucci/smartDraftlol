"""Tests de scoring: GlobalScore, PersonalScore y Confidence."""

from __future__ import annotations

from lol_reasoner.domain.enums import ALL_PHASES
from lol_reasoner.domain.query import MatchupQuery
from lol_reasoner.recommend import recommend
from lol_reasoner.scoring.weights import DEFAULT_WEIGHTS


def test_mastery_changes_personal_score_but_not_global_score(champions):
    query_low = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",), mastery={"mordekaiser": 0})
    query_high = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",), mastery={"mordekaiser": 100})

    rs_low = recommend(query_low, champions)
    rs_high = recommend(query_high, champions)

    rec_low = rs_low.recommendations["mordekaiser"]
    rec_high = rs_high.recommendations["mordekaiser"]

    assert rec_low.global_score == rec_high.global_score
    assert rec_low.personal_score != rec_high.personal_score
    assert rec_high.personal_score > rec_low.personal_score


def test_no_mastery_given_personal_equals_global(champions):
    query = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",))
    rs = recommend(query, champions)
    rec = rs.recommendations["mordekaiser"]
    assert rec.mastery is None
    assert rec.personal_score == rec.global_score


def test_global_score_is_within_bounds(champions):
    query = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",))
    rs = recommend(query, champions)
    rec = rs.recommendations["mordekaiser"]
    assert 0.0 <= rec.global_score <= 100.0
    assert 0.0 <= rec.personal_score <= 100.0


def test_global_score_does_not_read_mastery_from_query_dict_directly(champions):
    """Cambiar el mastery de un candidato que ni siquiera está en la
    consulta no debería alterar el score de otro candidato."""

    query_a = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",), mastery={})
    query_b = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",), mastery={"nadie": 99})
    rs_a = recommend(query_a, champions)
    rs_b = recommend(query_b, champions)
    assert rs_a.recommendations["mordekaiser"].global_score == rs_b.recommendations["mordekaiser"].global_score


def test_confidence_drops_with_contradictory_evidence(darius, mordekaiser):
    """darius vs mordekaiser mezcla evidencia PRO y CONTRA en mechanical_interaction
    dentro de una misma fase (p. ej. penetración/daño verdadero PRO vs
    mitigación por escudo CONTRA, ambos desde G03/G04): eso es justo un
    matchup condicional y la confianza no debería ser ALTA."""

    query = MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",))
    rs = recommend(query, {"darius": darius, "mordekaiser": mordekaiser})
    rec = rs.recommendations["darius"]
    assert rec.confidence.level != "alta"


def test_confidence_score_is_bounded(champions):
    query = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",))
    rs = recommend(query, champions)
    rec = rs.recommendations["mordekaiser"]
    assert 0.0 <= rec.confidence.score <= 1.0


def test_confidence_coverage_only_counts_categories_in_the_general_universe(darius, mordekaiser):
    """`missing_item_data` (el aviso fijo de FIRST_ITEM) y
    `specific_kit_exception` no son categorías de razonamiento mecánico
    general: no deben inflar el numerador de cobertura."""

    from lol_reasoner.reasoning.rules.registry import ALL_CATEGORIES

    query = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",))
    rs = recommend(query, {"darius": darius, "mordekaiser": mordekaiser})
    rec = rs.recommendations["mordekaiser"]

    categorias_citadas = {e["category"] for e in rec.trace_entries}
    assert "missing_item_data" in categorias_citadas  # se dispara (fase first_item), pero...
    expected_ratio = len(ALL_CATEGORIES & categorias_citadas) / len(ALL_CATEGORIES)
    assert rec.confidence.coverage_ratio == round(expected_ratio, 3)


def test_missing_info_is_deduplicated_across_phases(darius, mordekaiser):
    """Si la misma observación de información faltante aparece en varias
    fases, debe contar una sola vez, no una por fase."""

    from lol_reasoner.scoring.confidence import compute_confidence
    from lol_reasoner.reasoning.engine import RuleEngine

    trace = RuleEngine().build_trace(mordekaiser, darius, ALL_PHASES)
    distinct_texts = {e.invalidated_if for e in trace.entries if e.invalidated_if}
    raw_entry_count = sum(1 for e in trace.entries if e.invalidated_if)

    result = compute_confidence(trace)
    assert result.missing_info_count == len(distinct_texts)
    if raw_entry_count > len(distinct_texts):
        assert result.missing_info_count < raw_entry_count


def test_contradiction_is_scoped_to_phase_and_factor(darius, mordekaiser):
    """Una ventaja de early_lane y una desventaja de side_lane_late en el
    mismo factor no deben contarse como una contradicción: no son
    simultáneas."""

    from lol_reasoner.domain.enums import Factor, Phase, Polarity
    from lol_reasoner.reasoning.trace import ReasoningTrace, TraceEntry
    from lol_reasoner.scoring.confidence import compute_confidence

    trace = ReasoningTrace(candidate_id="x", enemy_id="y")
    trace.add(TraceEntry(
        id="a", rule_id="RX", rule_summary="s", category="phase_transition", phase=Phase.EARLY_LANE,
        factor=Factor.LANE_PATTERN, polarity=Polarity.PRO, delta=0.5, premises=(), subject="x", text="t1",
    ))
    trace.add(TraceEntry(
        id="b", rule_id="RX", rule_summary="s", category="phase_transition", phase=Phase.SIDE_LANE_LATE,
        factor=Factor.LANE_PATTERN, polarity=Polarity.CONTRA, delta=0.5, premises=(), subject="x", text="t2",
    ))
    result = compute_confidence(trace)
    assert result.contradiction_count == 0


def test_personal_score_required_skill_deduplicates_repeated_conditions(darius):
    """G09/G10/G11 ya están restringidas a una sola fase, pero este test
    documenta directamente el contrato: `conditional_entry_count` cuenta
    condiciones DISTINTAS, no entradas."""

    from lol_reasoner.domain.enums import Factor, Phase, Polarity
    from lol_reasoner.reasoning.trace import ReasoningTrace, TraceEntry
    from lol_reasoner.scoring.personal_score import conditional_entry_count

    trace = ReasoningTrace(candidate_id="x", enemy_id="y")
    for phase in (Phase.EARLY_LANE, Phase.LEVEL_6, Phase.FIRST_ITEM):
        trace.add(TraceEntry(
            id=f"a-{phase.value}", rule_id="RX", rule_summary="s", category="c", phase=phase,
            factor=Factor.RELIABILITY, polarity=Polarity.CONDITIONAL, delta=0.1, premises=(), subject="x",
            text="t", condition="la misma condición repetida",
        ))
    assert conditional_entry_count(trace) == 1
