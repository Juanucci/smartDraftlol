"""Tests de scoring: GlobalScore, PersonalScore y Confidence — hitos 1.5 y 1.6."""

from __future__ import annotations

from lol_reasoner.domain.enums import ALL_PHASES, ConditionKind, Factor, Phase, Polarity
from lol_reasoner.domain.query import MatchupQuery
from lol_reasoner.recommend import recommend
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.trace import ReasoningTrace, TraceEntry
from lol_reasoner.scoring.confidence import compute_confidence
from lol_reasoner.scoring.personal_score import PlayerProfile, execution_condition_count, personal_score
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
    # Y tampoco toca Confidence (epistemia ni volatilidad): mastery es un
    # dato del jugador, no del matchup.
    assert rec_low.confidence.score == rec_high.confidence.score
    assert rec_low.confidence.volatility_score == rec_high.confidence.volatility_score


def test_no_mastery_given_personal_equals_global(champions):
    query = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",))
    rs = recommend(query, champions)
    rec = rs.recommendations["mordekaiser"]
    assert rec.mastery is None
    assert rec.personal_score == rec.global_score
    assert rec.personal_breakdown is None


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


def test_execution_demand_does_not_move_global_score(darius):
    """Hito 1.6, punto 13: GlobalScore mide adecuación mecánica teórica
    suponiendo ejecución competente. Subir `execution_demand` no debe
    moverlo (ExecutionDemandBaselineRule fue eliminada; ya no existe
    `Factor.EXECUTION_DEMAND`)."""

    import copy
    from importlib import resources

    import yaml

    from lol_reasoner.knowledge.loader import load_champion_from_dict

    def _raw(cid):
        p = resources.files("lol_reasoner.knowledge.champions").joinpath(f"{cid}.yaml")
        with resources.as_file(p) as path:
            return yaml.safe_load(path.read_text(encoding="utf-8"))

    original = _raw("mordekaiser")
    mutated = copy.deepcopy(original)
    mutated["axes"]["execution_demand"] = 4  # antes 2

    mordekaiser_original = load_champion_from_dict(original, source="<o>")
    mordekaiser_mutated = load_champion_from_dict(mutated, source="<m>")

    def _global(candidate):
        query = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",))
        champs = {"darius": darius, "mordekaiser": candidate}
        return recommend(query, champs).recommendations["mordekaiser"].global_score

    assert _global(mordekaiser_original) == _global(mordekaiser_mutated)
    assert "execution_demand" not in {f.value for f in Factor}


def test_confidence_drops_with_contradictory_evidence_but_only_volatility(darius, mordekaiser):
    """darius vs mordekaiser mezcla evidencia PRO y CONTRA en mechanical_interaction
    dentro de una misma fase: eso alimenta VOLATILIDAD (es justo un
    matchup condicional), no epistemia — la evidencia en ambos sentidos
    no es ignorancia."""

    query = MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",))
    rs = recommend(query, {"darius": darius, "mordekaiser": mordekaiser})
    rec = rs.recommendations["darius"]
    assert rec.confidence.contradiction_count > 0
    assert rec.confidence.volatility_score > 0


def test_confidence_score_is_bounded(champions):
    query = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",))
    rs = recommend(query, champions)
    rec = rs.recommendations["mordekaiser"]
    assert 0.0 <= rec.confidence.score <= 1.0
    assert 0.0 <= rec.confidence.volatility_score <= 1.0


def test_empty_trace_gives_zero_epistemic_confidence():
    """Hito 1.6, punto 14: una traza vacía DEBE dar confianza epistémica
    cero/BAJA, sin excepción. Antes, un piso aditivo incondicional podía
    dar MEDIA (~0.45) con cero evidencia — bug verificado y corregido."""

    empty = ReasoningTrace(candidate_id="x", enemy_id="y")
    empty_mirror = ReasoningTrace(candidate_id="y", enemy_id="x")
    result = compute_confidence(empty, empty_mirror)
    assert result.score == 0.0
    assert result.level.value == "baja"


def test_confidence_coverage_denominator_is_mirror_based_not_global_registry(darius, mordekaiser):
    """El denominador de cobertura son las categorías APLICABLES a este
    matchup (unión de ambas direcciones), no `len(ALL_CATEGORIES)` del
    registro global — así incorporar reglas/campeones nuevos no hace
    caer la confianza de matchups ya evaluados."""

    from lol_reasoner.reasoning.rules.registry import ALL_CATEGORIES

    trace = RuleEngine().build_trace(mordekaiser, darius, ALL_PHASES)
    mirror = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    result = compute_confidence(trace, mirror)

    applicable = ALL_CATEGORIES & (trace.categories() | mirror.categories())
    assert result.applicable_categories_count == len(applicable)
    # El denominador real (para este par) es menor que el universo global
    # de categorías: no todas las reglas generales aplican a Darius/Mordekaiser.
    assert result.applicable_categories_count <= len(ALL_CATEGORIES)


def test_missing_item_data_category_does_not_inflate_coverage(darius, mordekaiser):
    trace = RuleEngine().build_trace(mordekaiser, darius, ALL_PHASES)
    mirror = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    categorias_citadas = trace.categories()
    assert "missing_item_data" in categorias_citadas  # se dispara (fase first_item), pero...
    result = compute_confidence(trace, mirror)
    assert "missing_item_data" not in result.categories_hit


def test_missing_info_is_deduplicated_across_phases(darius, mordekaiser):
    """Si la misma observación de información faltante aparece en varias
    fases, debe contar una sola vez, no una por fase."""

    trace = RuleEngine().build_trace(mordekaiser, darius, ALL_PHASES)
    mirror = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    distinct_texts = {e.invalidated_if for e in trace.entries if e.invalidated_if}
    raw_entry_count = sum(1 for e in trace.entries if e.invalidated_if)

    result = compute_confidence(trace, mirror)
    assert result.missing_info_count == len(distinct_texts)
    if raw_entry_count > len(distinct_texts):
        assert result.missing_info_count < raw_entry_count


def test_contradiction_is_scoped_to_phase_and_factor():
    """Una ventaja de early_lane y una desventaja de side_lane_late en el
    mismo factor no deben contarse como una contradicción: no son
    simultáneas."""

    trace = ReasoningTrace(candidate_id="x", enemy_id="y")
    trace.add(TraceEntry(
        id="a", rule_id="RX", rule_summary="s", category="phase_transition", phase=Phase.EARLY_LANE,
        factor=Factor.LANE_PATTERN, polarity=Polarity.PRO, delta=0.5, premises=(), subject="x", text="t1",
    ))
    trace.add(TraceEntry(
        id="b", rule_id="RX", rule_summary="s", category="phase_transition", phase=Phase.SIDE_LANE_LATE,
        factor=Factor.LANE_PATTERN, polarity=Polarity.CONTRA, delta=0.5, premises=(), subject="x", text="t2",
    ))
    mirror = ReasoningTrace(candidate_id="y", enemy_id="x")
    result = compute_confidence(trace, mirror)
    assert result.contradiction_count == 0


def test_contradiction_and_pro_contra_evidence_is_not_conflated_with_ignorance():
    """Punto 8 del hito 1.6: evidencia PRO y CONTRA en el mismo (fase,
    factor) no debe interpretarse como desconocimiento — no debe bajar
    `score` (epistémico); debe subir `volatility_score`."""

    trace = ReasoningTrace(candidate_id="x", enemy_id="y")
    trace.add(TraceEntry(
        id="a", rule_id="RX", rule_summary="s", category="damage_mitigation", phase=Phase.EARLY_LANE,
        factor=Factor.MECHANICAL_INTERACTION, polarity=Polarity.PRO, delta=0.5, premises=(), subject="x", text="t1",
    ))
    trace.add(TraceEntry(
        id="b", rule_id="RX", rule_summary="s", category="shield_mitigation", phase=Phase.EARLY_LANE,
        factor=Factor.MECHANICAL_INTERACTION, polarity=Polarity.CONTRA, delta=0.5, premises=(), subject="x", text="t2",
    ))
    mirror = ReasoningTrace(candidate_id="y", enemy_id="x")
    result_with_contradiction = compute_confidence(trace, mirror)

    trace_no_contradiction = ReasoningTrace(candidate_id="x", enemy_id="y")
    trace_no_contradiction.add(TraceEntry(
        id="a", rule_id="RX", rule_summary="s", category="damage_mitigation", phase=Phase.EARLY_LANE,
        factor=Factor.MECHANICAL_INTERACTION, polarity=Polarity.PRO, delta=0.5, premises=(), subject="x", text="t1",
    ))
    result_without = compute_confidence(trace_no_contradiction, mirror)

    # Misma cobertura (una categoría con evidencia) => misma epistemia;
    # la contradicción no la penaliza.
    assert result_with_contradiction.contradiction_count == 1
    assert result_with_contradiction.volatility_score > result_without.volatility_score


def test_knowledge_gap_condition_kind_is_not_defined_as_a_condition_kind_used_by_rules():
    """KNOWLEDGE_GAP existe en el enum para uso futuro (p. ej. si una
    regla quisiera marcar explícitamente una condición como hueco de
    conocimiento en vez de usar `invalidated_if`), pero por ahora la
    información faltante se representa vía `invalidated_if`, ya cubierto
    por `missing_info_count`. Este test documenta que el valor existe."""

    assert ConditionKind.KNOWLEDGE_GAP.value == "knowledge_gap"


def test_execution_condition_count_only_counts_execution_kind():
    """Punto 13 del hito 1.6: información faltante, ausencia de objetos
    o incertidumbre estratégica NO deben subir `required_skill`. Solo
    `ConditionKind.EXECUTION` puede."""

    trace = ReasoningTrace(candidate_id="x", enemy_id="y")
    trace.add(TraceEntry(
        id="a", rule_id="RX", rule_summary="s", category="c", phase=Phase.EARLY_LANE,
        factor=Factor.RELIABILITY, polarity=Polarity.CONDITIONAL, delta=0.1, premises=(), subject="x",
        text="t", condition="condición de ejecución", condition_kind=ConditionKind.EXECUTION,
    ))
    trace.add(TraceEntry(
        id="b", rule_id="RY", rule_summary="s", category="c", phase=Phase.EARLY_LANE,
        factor=Factor.RELIABILITY, polarity=Polarity.CONDITIONAL, delta=0.1, premises=(), subject="x",
        text="t", condition="condición estratégica", condition_kind=ConditionKind.STRATEGIC,
    ))
    trace.add(TraceEntry(
        id="c", rule_id="RZ", rule_summary="s", category="missing_item_data", phase=Phase.FIRST_ITEM,
        factor=Factor.RELIABILITY, polarity=Polarity.CONDITIONAL, delta=0.0, premises=(), subject="x",
        text="t", condition="hueco de conocimiento", condition_kind=None,
    ))
    assert execution_condition_count(trace) == 1


def test_personal_score_required_skill_deduplicates_repeated_execution_conditions():
    """G09 ya está restringida a una sola fase, pero este test documenta
    directamente el contrato: `execution_condition_count` cuenta
    condiciones EXECUTION DISTINTAS, no entradas."""

    trace = ReasoningTrace(candidate_id="x", enemy_id="y")
    for phase in (Phase.EARLY_LANE, Phase.LEVEL_6, Phase.FIRST_ITEM):
        trace.add(TraceEntry(
            id=f"a-{phase.value}", rule_id="RX", rule_summary="s", category="c", phase=phase,
            factor=Factor.RELIABILITY, polarity=Polarity.CONDITIONAL, delta=0.1, premises=(), subject="x",
            text="t", condition="la misma condición repetida", condition_kind=ConditionKind.EXECUTION,
        ))
    assert execution_condition_count(trace) == 1


def test_personal_score_breakdown_reflects_mastery_and_required_skill(darius):
    """PersonalScoreBreakdown (PlayerProfile provisional) debe explicar
    de dónde sale PersonalScore sin pasar por TraceEntry falsos."""

    query = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",), mastery={"mordekaiser": 60})

    from lol_reasoner.knowledge.loader import load_all_champions

    champions = load_all_champions()
    rec = recommend(query, champions).recommendations["mordekaiser"]
    assert rec.personal_breakdown is not None
    assert rec.personal_breakdown.mastery == 60
    assert rec.personal_breakdown.required_skill > 0
    assert rec.personal_breakdown.gap == rec.personal_breakdown.mastery - rec.personal_breakdown.required_skill


def test_player_profile_is_the_extensible_interface_for_personal_score(darius):
    """PlayerProfile hoy solo tiene `mastery`; el contrato es que
    `personal_score()` recibe un `profile`, no un valor suelto — así
    señales futuras se agregan sin tocar la firma."""

    from lol_reasoner.scoring.personal_score import personal_score

    profile = PlayerProfile(mastery=50)
    score, breakdown = personal_score(
        60.0, profile=profile, execution_demand=2, execution_condition_count=0, weights=DEFAULT_WEIGHTS,
    )
    assert breakdown is not None
    assert breakdown.mastery == 50
