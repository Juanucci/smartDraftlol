"""Verifica la regla de oro del proyecto: nada en la salida existe sin
una entrada de traza real que lo respalde, y todo cambio de score viene
de una entrada de traza."""

from __future__ import annotations

from lol_reasoner.domain.enums import Polarity
from lol_reasoner.domain.query import MatchupQuery
from lol_reasoner.recommend import recommend


def _recommendation_for(enemy_id: str, candidate_id: str, champions):
    query = MatchupQuery(enemy_id=enemy_id, candidate_ids=(candidate_id,))
    rs = recommend(query, champions)
    return rs.recommendations[candidate_id]


def test_every_reason_references_a_real_trace_entry(champions):
    rec = _recommendation_for("darius", "mordekaiser", champions)
    entry_ids = {e["id"] for e in rec.trace_entries}
    for item in rec.reasons:
        assert item.entry_id in entry_ids, f"razón sin entrada real: {item}"


def test_every_risk_references_a_real_trace_entry(champions):
    rec = _recommendation_for("darius", "mordekaiser", champions)
    entry_ids = {e["id"] for e in rec.trace_entries}
    for item in rec.risks:
        assert item.entry_id in entry_ids, f"riesgo sin entrada real: {item}"


def test_every_condition_references_a_real_trace_entry(champions):
    rec = _recommendation_for("mordekaiser", "darius", champions)
    entry_ids = {e["id"] for e in rec.trace_entries}
    for item in rec.conditions:
        assert item.entry_id in entry_ids, f"condición sin entrada real: {item}"


def test_every_missing_info_item_references_a_real_trace_entry(champions):
    rec = _recommendation_for("mordekaiser", "darius", champions)
    entry_ids = {e["id"] for e in rec.trace_entries}
    for item in rec.missing_info:
        assert item.entry_id in entry_ids, f"información faltante sin entrada real: {item}"


def test_reasons_text_matches_the_entry_it_references(champions):
    """No solo el id debe existir: el texto mostrado debe ser exactamente
    el texto de esa entrada (nada de texto libre desconectado del cálculo)."""

    rec = _recommendation_for("darius", "mordekaiser", champions)
    by_id = {e["id"]: e for e in rec.trace_entries}
    for item in rec.reasons:
        entry = by_id[item.entry_id]
        assert entry["text"] == item.text
        assert entry["polarity"] == Polarity.PRO.value


def test_risks_reference_contra_polarity_entries(champions):
    rec = _recommendation_for("darius", "mordekaiser", champions)
    by_id = {e["id"]: e for e in rec.trace_entries}
    for item in rec.risks:
        entry = by_id[item.entry_id]
        assert entry["polarity"] == Polarity.CONTRA.value


def test_conditions_reference_entries_that_actually_carry_that_condition(champions):
    rec = _recommendation_for("mordekaiser", "darius", champions)
    by_id = {e["id"]: e for e in rec.trace_entries}
    for item in rec.conditions:
        entry = by_id[item.entry_id]
        assert entry["condition"] == item.text


def test_factor_breakdown_only_has_nonzero_values_for_factors_with_scoring_entries(champions):
    """Todo cambio en el score (entrada en factor_breakdown) tiene que
    poder rastrearse a al menos una entrada PRO/CONTRA de ese factor en
    la traza."""

    rec = _recommendation_for("mordekaiser", "darius", champions)
    factors_with_entries = {
        e["factor"] for e in rec.trace_entries if e["polarity"] in (Polarity.PRO.value, Polarity.CONTRA.value)
    }
    for factor, value in rec.factor_breakdown.items():
        if abs(value) > 1e-9:
            assert factor in factors_with_entries, f"factor {factor}={value} sin entradas PRO/CONTRA que lo respalden"


def test_conditional_entries_never_move_the_global_score_by_themselves(champions):
    """Una entrada CONDITIONAL con delta>0 no debe, por sí sola, ser la
    única fuente de una contribución de factor no nula (su signo de score
    es 0 por diseño; ver scoring/global_score.py)."""

    rec = _recommendation_for("mordekaiser", "darius", champions)
    conditional_only_factors = set()
    scoring_factors = set()
    for e in rec.trace_entries:
        if e["polarity"] == Polarity.CONDITIONAL.value:
            conditional_only_factors.add(e["factor"])
        else:
            scoring_factors.add(e["factor"])
    # cualquier factor que tenga contribución no nula debe tener soporte no-condicional
    for factor, value in rec.factor_breakdown.items():
        if abs(value) > 1e-9:
            assert factor in scoring_factors
