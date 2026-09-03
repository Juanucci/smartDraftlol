"""Disciplina de vocabulario vivo (hito 1.5): todo `EffectType` presente
en el KB debe influir de verdad en la traza (evidencia comportamental,
no solo aparecer citado en código), y todo `TacticalUse` usado en el KB
debe ser leído literalmente por al menos una regla.

Esto es lo que impide repetir la situación del hito 1: campos cargados
y validados que ningún cálculo llegaba a leer (`available_from`,
`spikes`, `strengths`).
"""

from __future__ import annotations

import ast
import inspect

from lol_reasoner.domain.enums import ALL_PHASES, EffectType, TacticalUse
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.rules import general, stacking

# EffectType presentes en el KB que, por diseño, NUNCA deben mover ningún
# score en NINGÚN par de campeones (documentado en IsolationRule): su
# ausencia de efecto es la afirmación correcta, no vocabulario muerto.
ALWAYS_INERT_EFFECT_TYPES = frozenset({EffectType.ISOLATE_DUEL})

# EffectType consumidos por una regla real (DisplacementVsMobilityRule,
# G15) cuya condición de disparo — que el RIVAL tenga movilidad/disengage
# que negar — no se cumple para NINGUNA de las dos direcciones de este
# par específico: tanto Darius (mobility=0, disengage=0) como Mordekaiser
# (mobility=0, disengage=0) son duelistas sin ninguna movilidad que un
# desplazamiento/slow pudiera negar. Esto es "condicionalmente silencioso
# para este par", no vocabulario muerto: la regla existe, se ejecuta, y
# su comportamiento se verifica directamente en
# test_domain_model.py::test_apprehend_is_not_a_self_dash_and_does_not_apply_hemorrhage
# y test_domain_model.py::test_darius_w_represents_slow_autoreset_and_stack_acceleration.
# Se espera que esta lista se achique en cuanto se incorpore un campeón
# con movilidad/disengage real (p. ej. Jax, Kennen).
SILENT_FOR_THIS_PAIR_EFFECT_TYPES = frozenset({EffectType.DISPLACE_ENEMY, EffectType.BRIEF_CC, EffectType.SLOW})

DELIBERATELY_INERT_EFFECT_TYPES = ALWAYS_INERT_EFFECT_TYPES | SILENT_FOR_THIS_PAIR_EFFECT_TYPES


def _effect_types_in_kb(champions) -> set[EffectType]:
    types: set[EffectType] = set()
    for champ in champions.values():
        for ability in champ.abilities:
            types |= ability.effect_types()
        for mechanic in champ.stacking_mechanics:
            types |= {e.type for e in mechanic.reward_effects}
    return types


def _tactical_uses_in_kb(champions) -> set[TacticalUse]:
    uses: set[TacticalUse] = set()
    for champ in champions.values():
        for ability in champ.abilities:
            uses |= ability.tactical_uses
    return uses


def test_every_effect_type_in_kb_is_referenced_by_some_rule_source():
    """Chequeo mínimo de higiene: aunque la prueba fuerte es la
    comportamental de abajo, ningún EffectType usado en el KB debería
    estar completamente ausente del código fuente de las reglas."""

    from lol_reasoner.knowledge.loader import load_all_champions

    used_types = _effect_types_in_kb(load_all_champions())
    source = inspect.getsource(general) + inspect.getsource(stacking)
    referenced = {t for t in used_types if t.name in source}
    missing = used_types - referenced
    assert not missing, f"EffectType usados en el KB pero nunca nombrados en una regla: {missing}"


def test_every_effect_type_in_kb_influences_the_trace_or_is_documented_inert(champions):
    """Evidencia comportamental: cada EffectType presente en el KB debe
    aparecer citado en el `path` de al menos un `FactRef` de la traza real
    (en cualquiera de las dos direcciones), o estar en la lista explícita
    de inertes documentados."""

    used_types = _effect_types_in_kb(champions)

    engine = RuleEngine()
    trace_d = engine.build_trace(champions["darius"], champions["mordekaiser"], ALL_PHASES)
    trace_m = engine.build_trace(champions["mordekaiser"], champions["darius"], ALL_PHASES)

    cited_paths = " ".join(p.path for t in (trace_d, trace_m) for e in t.entries for p in e.premises)

    uninfluential = {
        t for t in used_types
        if t.value not in cited_paths and t not in DELIBERATELY_INERT_EFFECT_TYPES
    }
    assert not uninfluential, f"EffectType sin ninguna influencia observable en la traza: {uninfluential}"

    # y los deliberadamente inertes deben seguir citados en código (no removidos silenciosamente)
    source = inspect.getsource(general)
    for t in DELIBERATELY_INERT_EFFECT_TYPES & used_types:
        assert t.name in source, f"{t} está marcado inerte pero ya no se referencia en ninguna regla"


def test_every_tactical_use_in_kb_is_referenced_literally_by_some_rule(champions):
    used_uses = _tactical_uses_in_kb(champions)
    source = inspect.getsource(general) + inspect.getsource(stacking)
    missing = {u for u in used_uses if u.name not in source}
    assert not missing, f"TacticalUse usados en el KB pero ninguna regla los lee: {missing}"


def test_no_active_tag_members_go_unused():
    """Tag está vacío en este hito; si alguna vez se activa un miembro,
    este test exige que además exista un consumidor (mismo criterio que
    EffectType/TacticalUse). Con el enum vacío, el test es trivial pero
    documenta la expectativa para cuando se active el primero."""

    from lol_reasoner.domain.enums import Tag

    assert list(Tag) == [], "si se activó un Tag, agregar acá su verificación de consumo real"


def test_no_dead_ast_literals_for_champion_identity_in_general_rules():
    """Guardrail complementario: ningún literal string coincide con un id
    o nombre de campeón dentro de general.py/stacking.py (ver también
    test_no_hardcoded_pairs.py, que es la prueba principal de esto)."""

    from lol_reasoner.knowledge.loader import load_all_champions

    champions = load_all_champions()
    forbidden = {c.id for c in champions.values()} | {c.id.capitalize() for c in champions.values()}
    for module in (general, stacking):
        tree = ast.parse(inspect.getsource(module))
        literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        hit = forbidden & literals
        assert not hit, f"{module.__name__} contiene literales de campeón: {hit}"
