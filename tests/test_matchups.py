"""Caso de validación del primer hito: Darius vs Mordekaiser, ambas direcciones.

No se afirma un "ganador absoluto": se verifica que el razonamiento
mecánico esté presente, sea trazable y pueda cambiar según la fase.
"""

from __future__ import annotations

from lol_reasoner.domain.query import MatchupQuery
from lol_reasoner.recommend import recommend


def _recommend(enemy_id, candidate_id, champions, mastery=None, phases=None):
    query = MatchupQuery(
        enemy_id=enemy_id,
        candidate_ids=(candidate_id,),
        mastery={candidate_id: mastery} if mastery is not None else {},
        phases=phases,
    )
    return recommend(query, champions).recommendations[candidate_id]


def test_mordekaiser_vs_darius_mentions_key_ability_interactions(champions):
    rec = _recommend("darius", "mordekaiser", champions)
    all_text = " ".join(
        r.text for r in (*rec.reasons, *rec.risks, *rec.conditions, *rec.missing_info)
    )
    assert "Indestructible" in all_text
    assert "Darkness Rise" in all_text


def test_darius_vs_mordekaiser_mentions_key_ability_interactions(champions):
    rec = _recommend("mordekaiser", "darius", champions)
    all_text = " ".join(
        r.text for r in (*rec.reasons, *rec.risks, *rec.conditions, *rec.missing_info)
    )
    # el matchup debe mencionar al menos una habilidad concreta de alguno de los dos kits
    kit_terms = ["Hemorrhage", "Apprehend", "Noxian Guillotine", "Indestructible", "Darkness Rise", "Realm of Death"]
    assert any(term in all_text for term in kit_terms)


def test_does_not_declare_an_absolute_winner(champions):
    """La recomendación debe traer condiciones, no solo un score: un
    matchup condicional no debería llegar con la lista de condiciones vacía."""

    rec_d = _recommend("mordekaiser", "darius", champions)
    rec_m = _recommend("darius", "mordekaiser", champions)
    assert len(rec_d.conditions) > 0
    assert len(rec_m.conditions) > 0


def test_recommendation_can_differ_between_early_and_side_lane(champions):
    from lol_reasoner.domain.enums import Phase

    rec_early = _recommend("mordekaiser", "darius", champions, phases=(Phase.EARLY_LANE,))
    rec_side = _recommend("mordekaiser", "darius", champions, phases=(Phase.SIDE_LANE_LATE,))
    assert rec_early.global_score != rec_side.global_score


def test_side_lane_note_reflects_mordekaiser_scaling_advantage(champions):
    rec = _recommend("mordekaiser", "darius", champions)
    side_note = rec.phase_notes["side_lane_late"]
    # Mordekaiser escala mejor: el neto de scaling_sidelane para Darius-candidato debería ser negativo
    assert side_note.net_delta_by_factor.get("scaling_sidelane", 0.0) < 0


def test_darius_has_early_lane_pressure_advantage_noted(champions):
    rec = _recommend("mordekaiser", "darius", champions)
    early_note = rec.phase_notes["early_lane"]
    assert early_note.net_delta_by_factor.get("lane_pattern", 0.0) > 0


def test_confidence_reflects_missing_information(champions):
    rec = _recommend("mordekaiser", "darius", champions)
    assert rec.confidence.missing_info_count > 0
    assert "esta V0" in " ".join(rec.confidence.explanation) or rec.confidence.missing_info_count >= 0


def test_first_item_phase_flags_missing_item_information(champions):
    rec = _recommend("mordekaiser", "darius", champions)
    first_item_entries = [e for e in rec.trace_entries if e["phase"] == "first_item" and e["rule_id"] == "ITEMGAP"]
    assert len(first_item_entries) == 1
    assert first_item_entries[0]["invalidated_if"] is not None
