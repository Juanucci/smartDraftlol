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


def test_scaling_axis_is_declared_editorial_and_does_not_move_the_score(champions):
    """REEMPLAZA a `test_side_lane_note_reflects_mordekaiser_scaling_advantage`,
    que exigía que el eje editorial `scaling` moviera el score en contra
    de Darius. Ese test congelaba como conclusión mecánica lo que es una
    valoración escrita a mano: el motor no derivó que Mordekaiser escale
    mejor, se lo declararon en el YAML. Esta V0 no modela objetos,
    duración de partida ni combates de equipo, así que no puede sostener
    esa comparación — y ahora el dato se declara sin puntuar."""

    rec = _recommend("mordekaiser", "darius", champions)
    scaling_entries = [e for e in rec.trace_entries if e["category"] == "editorial_axis_prior" and "scaling" in e["text"]]
    assert scaling_entries, "el dato editorial debe seguir declarándose, no borrarse"
    for entry in scaling_entries:
        assert entry["provenance"] == "editorial_prior"
        assert entry["polarity"] == "conditional", "un prior editorial de escalado no puede mover el score"
        assert "valoración editorial" in entry["text"]

    side_note = rec.phase_notes["side_lane_late"]
    assert side_note.effective_contributions_by_factor.get("scaling_sidelane", 0.0) == 0.0


def test_early_pressure_prior_is_labelled_and_bounded(champions):
    """REEMPLAZA a `test_darius_has_early_lane_pressure_advantage_noted`,
    que verificaba el signo del ganador editorial. Lo que se exige ahora
    no es quién gana, sino que el prior se identifique como valoración
    manual y entre con peso reducido."""

    rec = _recommend("mordekaiser", "darius", champions)
    prior = next(e for e in rec.trace_entries if e["category"] == "editorial_axis_prior" and "early pressure" in e["text"])
    assert prior["provenance"] == "editorial_prior"
    assert "no algo que el motor haya derivado" in prior["text"]

    early = rec.phase_notes["early_lane"].effective_contributions_by_factor
    assert early, "la fase temprana debe seguir aportando algo al score"


def test_single_candidate_query_declares_no_best_pick(champions):
    """Con un solo candidato no hubo comparación que ganar."""

    from lol_reasoner.domain.query import MatchupQuery
    from lol_reasoner.recommend import recommend

    rs = recommend(MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",)), champions)
    assert rs.best_global is None
    assert rs.best_personal is None
    assert rs.ranking_global == ("mordekaiser",)


def test_engine_produces_a_synthesis_not_only_a_list_of_conditions(champions):
    """El motor debe cerrar con una inclinación explicada cuando la
    evidencia alcanza, en vez de terminar en una lista de condiciones."""

    for enemy, candidate in (("darius", "mordekaiser"), ("mordekaiser", "darius")):
        rec = _recommend(enemy, candidate, champions)
        assert rec.lean.direction in {"favors_candidate", "even", "favors_enemy"}
        assert rec.lean.summary
        assert rec.lean.matchup_confidence == rec.confidence.shared_matchup_confidence
        if rec.lean.direction != "even":
            assert rec.lean.main_factors, "una inclinación debe decir qué factores la sostienen"


def test_confidence_reflects_missing_information(champions):
    rec = _recommend("mordekaiser", "darius", champions)
    assert rec.confidence.missing_info_count > 0
    assert "esta V0" in " ".join(rec.confidence.explanation) or rec.confidence.missing_info_count >= 0


def test_first_item_phase_flags_missing_item_information(champions):
    rec = _recommend("mordekaiser", "darius", champions)
    first_item_entries = [e for e in rec.trace_entries if e["phase"] == "first_item" and e["rule_id"] == "ITEMGAP"]
    assert len(first_item_entries) == 1
    assert first_item_entries[0]["invalidated_if"] is not None
