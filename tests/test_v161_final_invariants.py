"""Invariantes de la ronda final de v1.6.1.

Cada test de acá corresponde a una corrección concreta pedida en la
revisión de las trazas: qué puede y qué no puede decidir el score, qué
tiene que seguir siendo visible aunque no puntúe, y qué afirmaciones no
puede volver a hacer el motor.

Ninguno congela un ganador, un score exacto ni una conclusión editorial:
todos verifican relaciones estructurales o invariantes de dirección.
"""

from __future__ import annotations

import copy
from importlib import resources

import pytest
import yaml

from lol_reasoner.domain.enums import (
    ALL_PHASES,
    EffectType,
    Phase,
    Polarity,
    Provenance,
    Support,
)
from lol_reasoner.domain.query import MatchupQuery
from lol_reasoner.knowledge.loader import load_champion_from_dict
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.recommend import recommend
from lol_reasoner.scoring.confidence import compute_confidence
from lol_reasoner.scoring.global_score import signed_contribution
from lol_reasoner.scoring.weights import DEFAULT_WEIGHTS


def _raw(champion_id: str) -> dict:
    path = resources.files("lol_reasoner.knowledge.champions").joinpath(f"{champion_id}.yaml")
    with resources.as_file(path) as p:
        return yaml.safe_load(p.read_text(encoding="utf-8"))


def _both_directions(champions):
    engine = RuleEngine()
    return (
        ("darius", engine.build_trace(champions["darius"], champions["mordekaiser"], ALL_PHASES)),
        ("mordekaiser", engine.build_trace(champions["mordekaiser"], champions["darius"], ALL_PHASES)),
    )


# ------------------------------------------------------------------ 1


def test_editorial_priors_are_visible_but_never_move_the_score(champions):
    """Un eje escrito a mano no puede decidir un veredicto mecánico, pero
    tampoco puede desaparecer: se conserva íntegro y etiquetado."""

    for subject, trace in _both_directions(champions):
        editorial = [e for e in trace.deduped_for_scoring(subject) if e.provenance == Provenance.EDITORIAL_PRIOR]
        assert editorial, f"{subject}: los priors editoriales deben seguir declarándose"
        for entry in editorial:
            assert signed_contribution(entry, DEFAULT_WEIGHTS) == 0.0
            assert entry.text


def test_removing_the_editorial_prior_does_not_change_the_score(champions):
    """La prueba de fondo: si el resultado cambiara al quitar el prior, la
    ventaja publicada no sería mecánica. Se muta el eje en memoria."""

    darius = load_champion_from_dict(_raw("darius"), source="<d>")
    mutated_raw = copy.deepcopy(_raw("darius"))
    mutated_raw["axes"]["early_pressure"] = 0  # antes 4
    darius_flat = load_champion_from_dict(mutated_raw, source="<flat>")
    mordekaiser = load_champion_from_dict(_raw("mordekaiser"), source="<m>")

    query = MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",))
    base = recommend(query, {"darius": darius, "mordekaiser": mordekaiser}).recommendations["darius"]
    flat = recommend(query, {"darius": darius_flat, "mordekaiser": mordekaiser}).recommendations["darius"]

    assert base.global_score == flat.global_score, (
        "el MatchupScore mecánico no puede moverse al cambiar una valoración editorial"
    )
    assert base.lean.direction == flat.lean.direction


def test_editorial_priors_have_their_own_output_channel(champions):
    """No se mezclan con la evidencia derivada del kit."""

    rec = recommend(
        MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",)), champions
    ).recommendations["darius"]
    assert rec.editorial_priors
    derived_ids = {r.entry_id for r in (*rec.reasons, *rec.risks)}
    editorial_ids = {r.entry_id for r in rec.editorial_priors}
    assert not (derived_ids & editorial_ids)


# ------------------------------------------------------------------ 2


def test_both_penetrations_appear_reciprocally_with_zero_effective_contribution(champions):
    """Ambas penetraciones son fortalezas reales y deben verse en las dos
    direcciones, como ventaja del dueño y riesgo del rival — pero sin
    mover el score: compartir `magnitude: 1` no demuestra igual
    intensidad, disponibilidad ni relevancia."""

    engine = RuleEngine()
    keys = ("darius:E:armor_penetration", "mordekaiser:E:magic_penetration")
    seen: dict[str, dict[str, object]] = {}
    for subject, trace in _both_directions(champions):
        by_key = {e.causal_key: e for e in trace.deduped_for_scoring(subject) if e.causal_key}
        for key in keys:
            assert key in by_key, f"{key} debe aparecer en la dirección de {subject}"
            entry = by_key[key]
            assert signed_contribution(entry, DEFAULT_WEIGHTS) == 0.0, f"{key} no debe mover el score"
            assert entry.support == Support.STRUCTURAL, "la penetración existe: no es ambigua"
            assert entry.invalidated_if, "debe declarar por qué su impacto no está cuantificado"
            seen.setdefault(key, {})[subject] = entry.polarity

    for key in keys:
        assert set(seen[key].values()) == {Polarity.PRO, Polarity.CONTRA}, f"{key} debe ser recíproca"


def test_penetrations_stay_visible_in_the_output(champions):
    rec = recommend(
        MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",)), champions
    ).recommendations["darius"]
    text = " ".join(r.text for r in rec.uncalibrated_observations)
    assert "penetra" in text, "una fortaleza real no puede desaparecer de la salida por no estar calibrada"


# ------------------------------------------------------------------ 3


def test_noxian_might_keeps_bonus_ad_and_r_keeps_its_stack_scaling(darius):
    mechanic = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    bonus = [e for e in mechanic.reward_effects if e.type == EffectType.BONUS_ATTACK_DAMAGE]
    assert len(bonus) == 1 and bonus[0].scope == "offensive_profile"

    r_scaling = [e for e in darius.ability("R").effects if e.stack_scaling == "hemorrhage"]
    assert len(r_scaling) == 1 and r_scaling[0].type == EffectType.DAMAGE


def test_the_reward_does_not_produce_one_entry_per_empowered_ability(champions):
    """Un solo pago, una sola causa: el empoderamiento ofensivo general no
    puede generar una ventaja de score por cada habilidad a la que llega."""

    trace = RuleEngine().build_trace(champions["darius"], champions["mordekaiser"], ALL_PHASES)
    payoff = [
        e for e in trace.deduped_for_scoring("darius")
        if e.category == "stack_race_payoff" and signed_contribution(e, DEFAULT_WEIGHTS)
    ]
    assert len(payoff) == 1


# ------------------------------------------------------------------ 4


def test_darius_w_actually_changes_the_short_trade_resolution():
    """Prueba CONDUCTUAL, no de texto: quitar en memoria el reset o el
    slow debe cambiar las premisas o la resolución de la situación B."""

    mordekaiser = load_champion_from_dict(_raw("mordekaiser"), source="<m>")

    def _short_trade(darius_raw):
        darius = load_champion_from_dict(darius_raw, source="<d>")
        trace = RuleEngine().build_trace(darius, mordekaiser, (Phase.EARLY_LANE,))
        return next(e for e in trace.entries if e.category == "stack_race_short_trade")

    base = _short_trade(_raw("darius"))

    without_reset = copy.deepcopy(_raw("darius"))
    for ability in without_reset["abilities"]:
        if ability["slot"] == "W":
            ability["effects"] = [e for e in ability["effects"] if e["type"] != "auto_attack_reset"]
    no_reset = _short_trade(without_reset)

    without_slow = copy.deepcopy(_raw("darius"))
    for ability in without_slow["abilities"]:
        if ability["slot"] == "W":
            ability["effects"] = [e for e in ability["effects"] if e["type"] != "slow"]
    no_slow = _short_trade(without_slow)

    base_paths = {p.path for p in base.premises}
    assert base_paths != {p.path for p in no_reset.premises}, "quitar el reset debe cambiar las premisas de B"
    assert base_paths != {p.path for p in no_slow.premises}, "quitar el slow debe cambiar las premisas de B"
    assert base.text != no_reset.text
    assert base.text != no_slow.text


def test_crippling_strike_does_not_add_a_second_scoring_cause(champions):
    trace = RuleEngine().build_trace(champions["darius"], champions["mordekaiser"], ALL_PHASES)
    scoring_keys = [
        e.causal_key for e in trace.deduped_for_scoring("darius") if signed_contribution(e, DEFAULT_WEIGHTS)
    ]
    assert len(scoring_keys) == len(set(scoring_keys))


# ------------------------------------------------------------------ 5


def test_realm_of_death_produces_the_geometry_observation_in_both_directions(champions):
    """La arena restringida, el trade que tiende a extenderse, la ausencia
    de oleada y que ambos puedan completar su acumulación: recíproco, sin
    score y sin afirmar que favorece automáticamente a su dueño."""

    for subject, trace in _both_directions(champions):
        arena = [e for e in trace.deduped_for_scoring(subject) if e.category == "isolation_arena"]
        assert len(arena) == 1, f"{subject}: falta la observación de geometría"
        entry = arena[0]
        assert entry.support == Support.CONDITIONED
        assert signed_contribution(entry, DEFAULT_WEIGHTS) == 0.0
        assert "no favorece automáticamente" in (entry.condition or "")
        assert "objetivo único" in entry.text
        assert "pueden llegar a completarse" in entry.text
        assert "ayuda externa" not in entry.text, "esta consulta ya es un 1v1: no se re-puntúa perder ayuda"


# ------------------------------------------------------------------ 6


def test_resourceless_ability_is_an_observation_not_a_poke_advantage(champions):
    for subject, trace in _both_directions(champions):
        entries = [e for e in trace.deduped_for_scoring(subject) if e.category == "resource_attrition"]
        for entry in entries:
            assert signed_contribution(entry, DEFAULT_WEIGHTS) == 0.0
            assert "no consume un recurso limitado" in entry.text
            assert "cooldown" in entry.text and "acertarla" in entry.text
            assert "campeón de poke" not in entry.text
            assert "infinito" not in entry.text


# ------------------------------------------------------------------ 7


def test_shared_matchup_confidence_does_not_change_when_inverting_the_query(champions):
    """"A tiene ventaja sobre B" es la misma afirmación se consulte desde
    donde se consulte: su confianza no puede depender de quién es el
    candidato. La cobertura individual sí puede diferir."""

    engine = RuleEngine()
    d = engine.build_trace(champions["darius"], champions["mordekaiser"], ALL_PHASES)
    m = engine.build_trace(champions["mordekaiser"], champions["darius"], ALL_PHASES)

    forward = compute_confidence(d, m)
    backward = compute_confidence(m, d)
    assert forward.shared_matchup_confidence == backward.shared_matchup_confidence
    assert forward.shared_strategic_volatility_score == backward.shared_strategic_volatility_score


def test_coverage_alta_does_not_imply_a_confident_verdict(champions):
    """Cobertura y certeza son preguntas distintas. Mientras la KB no esté
    auditada y los pesos no estén calibrados, el veredicto no puede
    anunciarse como ALTA por mucha cobertura que haya."""

    rec = recommend(
        MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",)), champions
    ).recommendations["mordekaiser"]

    assert rec.confidence.shared_matchup_confidence != "alta"
    assert rec.confidence.shared_matchup_confidence_reasons
    razones = " ".join(rec.confidence.shared_matchup_confidence_reasons)
    assert "auditado" in razones and "calibrad" in razones


# ------------------------------------------------------------------ 8


@pytest.mark.parametrize(
    ("enemy", "candidate"),
    [("mordekaiser", "darius"), ("darius", "mordekaiser")],
)
def test_synthesis_is_written_from_the_evaluated_candidates_perspective(champions, enemy, candidate):
    rec = recommend(
        MatchupQuery(enemy_id=enemy, candidate_ids=(candidate,)), champions
    ).recommendations[candidate]
    summary = rec.lean.summary
    name = rec.candidate_name

    assert name in summary, "la síntesis debe hablar del candidato evaluado"
    if rec.lean.direction == "favors_candidate":
        assert f"a favor de {name}" in summary
    elif rec.lean.direction == "favors_enemy":
        assert f"en contra de {name}" in summary


def test_reversal_conditions_have_explicit_subjects(champions):
    """Nada de "qué podría reducirla o invertirla": cada bloque dice a
    quién beneficia."""

    rec = recommend(
        MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",)), champions
    ).recommendations["mordekaiser"]
    if rec.lean.direction != "even":
        assert rec.lean.favored_name and rec.lean.other_name
        assert rec.lean.favored_name != rec.lean.other_name


# ------------------------------------------------------------------ 9


def test_phase_notes_report_new_causes_not_total_absence(champions):
    """Cero aportes nuevos en una fase no significa que las interacciones
    anteriores dejen de existir."""

    rec = recommend(
        MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",)), champions
    ).recommendations["darius"]
    late = rec.phase_notes["side_lane_late"]
    assert late.raw_entry_count > 0, "la fase sigue registrando interacciones vigentes"
    assert "no significa que las interacciones anteriores dejen de existir" in late.summary


def test_no_test_freezes_a_winner_or_an_exact_score():
    """Guardrail sobre los propios tests: ninguno puede volver a fijar un
    ganador, un score exacto ni una conclusión editorial."""

    import pathlib
    import re

    # Solo sentencias `assert` reales: los docstrings que EXPLICAN por qué
    # se eliminó un test viejo (p. ej. el `magnitude == 9`) son
    # documentación, no una afirmación congelada.
    forbidden = re.compile(
        r"^assert\s+.*(?:"
        r"global_score\s*==\s*\d"
        r"|magnitude\s*==\s*9\b"
        r"|\bwinner\b"
        r")"
    )
    offenders = []
    for path in pathlib.Path("tests").glob("test_*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if forbidden.search(stripped):
                offenders.append(f"{path.name}:{number}: {stripped}")
    assert not offenders, "tests que congelan un resultado en vez de una relación:\n  " + "\n  ".join(offenders)
