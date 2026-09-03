"""Tests del hito 1.5, puntos 3, 4 y 5: `available_from` se cumple
estructuralmente, y un escudo común puede absorber daño verdadero sin
que eso lo convierta en un "counter total"."""

from __future__ import annotations

import ast
import inspect

from lol_reasoner.domain.enums import ALL_PHASES, Phase
from lol_reasoner.reasoning.context import ReasoningContext
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.rules import general, stacking


def test_r_is_not_available_in_early_lane(darius):
    ctx = ReasoningContext(candidate=darius, enemy=darius, phase=Phase.EARLY_LANE)
    assert "R" not in {a.slot for a in ctx.candidate_abilities()}


def test_r_is_available_from_level_6(darius):
    ctx = ReasoningContext(candidate=darius, enemy=darius, phase=Phase.LEVEL_6)
    assert "R" in {a.slot for a in ctx.candidate_abilities()}


_CHAMPION_LIKE_NAMES = {"candidate", "enemy"}


def test_no_rule_accesses_champion_abilities_directly():
    """`available_from` se cumple estructuralmente: dentro de una regla,
    ningún acceso a `ctx.candidate`/`ctx.enemy` (o variables locales
    `candidate`/`enemy`) puede leer `.abilities` directo — deben pasar
    siempre por `ctx.candidate_abilities()` / `ctx.enemy_abilities()`.

    Las funciones auxiliares de `stacking.py` (`accelerator_abilities`,
    `reward_magnitude`) SÍ reciben un `Champion` genérico (parámetro
    `champion`, no `candidate`/`enemy`) porque deben poder aplicarse
    indistintamente al candidato o al enemigo — y filtran por fase ellas
    mismas con `is_available_in`, verificado por
    test_reward_magnitude_is_phase_gated en test_stacking.py. Por eso el
    escaneo excluye específicamente el nombre `champion`."""

    for module in (general, stacking):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute) and node.attr == "abilities"):
                continue
            base = node.value
            is_champion_like = (isinstance(base, ast.Attribute) and base.attr in _CHAMPION_LIKE_NAMES) or (
                isinstance(base, ast.Name) and base.id in _CHAMPION_LIKE_NAMES
            )
            if is_champion_like:
                raise AssertionError(
                    f"{module.__name__} accede a `.abilities` directo sobre candidate/enemy en línea {node.lineno}"
                )


def test_true_damage_grants_no_advantage_before_level_6(darius, mordekaiser):
    """El daño verdadero de Noxian Guillotine no debe generar ninguna
    entrada de la categoría true_damage_value en early_lane: la R no
    está disponible todavía."""

    trace = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    early_true_damage_entries = [
        e for e in trace.for_phase(Phase.EARLY_LANE) if e.category == "true_damage_value"
    ]
    assert not early_true_damage_entries

    level6_true_damage_entries = [
        e for e in trace.for_phase(Phase.LEVEL_6) if e.category == "true_damage_value"
    ]
    assert level6_true_damage_entries, "desde level_6 sí debería aparecer"


def test_common_shield_can_absorb_noxian_guillotine(darius, mordekaiser):
    """Un escudo común (Indestructible) puede absorber daño de Darius,
    incluido el componente verdadero de Noxian Guillotine, desde que R
    está disponible (level_6+). No debe existir ninguna regla que
    declare que el daño verdadero atraviesa este escudo."""

    trace = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    level6_shield_entries = [
        e for e in trace.for_phase(Phase.LEVEL_6) if e.category == "shield_mitigation"
    ]
    assert level6_shield_entries, "debería existir una entrada de mitigación por escudo desde level_6"
    assert any("Indestructible" in e.text for e in level6_shield_entries)
    assert any("verdadero" in e.text for e in level6_shield_entries)


def test_true_damage_does_not_bypass_the_shield(darius, mordekaiser):
    """No debe existir ninguna entrada de traza (en ninguna fase) que
    afirme que el daño verdadero ignora o atraviesa el escudo."""

    trace = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    forbidden_fragments = ("ignora el escudo", "atraviesa el escudo", "no lo mitiga")
    for entry in trace.entries:
        for fragment in forbidden_fragments:
            assert fragment not in entry.text.lower()
