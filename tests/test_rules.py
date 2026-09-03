"""Tests de reglas y del engine que arma la traza."""

from __future__ import annotations

from lol_reasoner.domain.enums import ALL_PHASES, Phase, Polarity
from lol_reasoner.reasoning.engine import RuleEngine


def test_trace_is_not_empty_for_darius_vs_mordekaiser(darius, mordekaiser):
    trace = RuleEngine().build_trace(mordekaiser, darius, ALL_PHASES)
    assert len(trace.entries) > 0


def test_every_entry_belongs_to_a_known_phase(darius, mordekaiser):
    trace = RuleEngine().build_trace(mordekaiser, darius, ALL_PHASES)
    for entry in trace.entries:
        assert entry.phase in ALL_PHASES


def test_analysis_differs_by_phase(darius, mordekaiser):
    """El análisis puede cambiar según la fase: level_6 y side_lane_late no
    deberían producir el mismo conjunto de entradas que early_lane."""

    trace = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    early = {e.text for e in trace.for_phase(Phase.EARLY_LANE)}
    side = {e.text for e in trace.for_phase(Phase.SIDE_LANE_LATE)}
    level6 = {e.text for e in trace.for_phase(Phase.LEVEL_6)}
    assert early != side
    assert early != level6


def test_isolation_and_execute_rules_only_appear_from_level_6(darius, mordekaiser):
    trace = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    early_categories = {e.category for e in trace.for_phase(Phase.EARLY_LANE)}
    assert "ultimate_impact" not in early_categories
    level6_categories = {e.category for e in trace.for_phase(Phase.LEVEL_6)}
    assert "ultimate_impact" in level6_categories


def test_directionality_darius_vs_mordekaiser_is_not_a_mirror(darius, mordekaiser):
    """Evaluar (darius candidato, mordekaiser enemigo) y (mordekaiser candidato,
    darius enemigo) debe producir texto distinto: el motor no debe copiar
    ciegamente el resultado de A→B para B→A."""

    trace_d_vs_m = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    trace_m_vs_d = RuleEngine().build_trace(mordekaiser, darius, ALL_PHASES)

    texts_d = {e.text for e in trace_d_vs_m.entries}
    texts_m = {e.text for e in trace_m_vs_d.entries}
    assert texts_d != texts_m

    # y el "subject" de cada traza es el candidato correspondiente, no el enemigo
    assert all(e.subject == "darius" for e in trace_d_vs_m.entries)
    assert all(e.subject == "mordekaiser" for e in trace_m_vs_d.entries)


def test_item_gap_disclaimer_only_appears_in_first_item_phase(darius, mordekaiser):
    trace = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    item_gap_entries = [e for e in trace.entries if e.rule_id == "ITEMGAP"]
    assert len(item_gap_entries) == 1
    assert item_gap_entries[0].phase == Phase.FIRST_ITEM


def test_no_entries_outside_requested_phases(darius, mordekaiser):
    trace = RuleEngine().build_trace(darius, mordekaiser, (Phase.EARLY_LANE,))
    assert all(e.phase == Phase.EARLY_LANE for e in trace.entries)
    assert len(trace.entries) > 0
