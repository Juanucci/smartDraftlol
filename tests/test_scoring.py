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
    (S01 true-damage-bypass PRO vs G04 Indestructible-niega-sostenido CONTRA):
    eso es justo un matchup condicional y la confianza no debería ser ALTA."""

    query = MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",))
    rs = recommend(query, {"darius": darius, "mordekaiser": mordekaiser})
    rec = rs.recommendations["darius"]
    assert rec.confidence.level != "alta"


def test_confidence_score_is_bounded(champions):
    query = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",))
    rs = recommend(query, champions)
    rec = rs.recommendations["mordekaiser"]
    assert 0.0 <= rec.confidence.score <= 1.0
