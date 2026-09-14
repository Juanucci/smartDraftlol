"""Tests del modelo tipado de estado (v1.7, Etapa 1 — endurecida).

Cubren únicamente el modelo de dominio en `domain/combat_state.py`: su
composición, sus invariantes de construcción, la inmutabilidad real de
sus mappings internos, y la distinción entre clave ausente / valor
desconocido / cero conocido / valor concreto. No hay secuencias,
generador de escenarios, invalidadores concretos, daño, timestamps,
ticks, ganador ni score en este archivo — esa es una etapa distinta.
"""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from types import MappingProxyType

import pytest

from lol_reasoner.domain.combat_state import (
    MAX_LEVEL,
    MIN_LEVEL,
    AbilityAvailability,
    AbilityState,
    ActionContext,
    ActorState,
    CombatState,
    HealthBand,
    InvalidatorStatus,
    IsolationStatus,
    PushDirection,
    RangeStatus,
    ReserveBand,
    ResourceBand,
    ResourceKind,
    RewardState,
    SharedContext,
    StackState,
    StackWindow,
    WaveState,
    WaveStateKind,
    combat_state_to_primitive,
)

# --- composición de CombatState ---------------------------------------------


def test_combat_state_composes_candidate_enemy_and_shared_context():
    state = CombatState(candidate=ActorState(), enemy=ActorState())

    assert isinstance(state.candidate, ActorState)
    assert isinstance(state.enemy, ActorState)
    assert isinstance(state.shared, SharedContext)


def test_combat_state_default_shared_context_is_fully_unknown():
    state = CombatState(candidate=ActorState(), enemy=ActorState())

    assert state.shared.wave_state.state is WaveStateKind.UNKNOWN
    assert state.shared.wave_state.pushing_toward is PushDirection.UNKNOWN
    assert dict(state.shared.action_contexts) == {}


def test_combat_state_accepts_explicit_shared_context():
    shared = SharedContext(wave_state=WaveState(state=WaveStateKind.PRESENT_NEUTRAL))
    state = CombatState(candidate=ActorState(), enemy=ActorState(), shared=shared)

    assert state.shared.wave_state.state is WaveStateKind.PRESENT_NEUTRAL


def test_combat_state_is_frozen():
    state = CombatState(candidate=ActorState(), enemy=ActorState())
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.candidate = ActorState(level=6)  # type: ignore[misc]


def test_combat_state_rejects_wrong_types_for_actors_and_shared():
    with pytest.raises(TypeError):
        CombatState(candidate="not an actor", enemy=ActorState())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        CombatState(candidate=ActorState(), enemy=ActorState(), shared="not shared")  # type: ignore[arg-type]


# --- nivel exacto ------------------------------------------------------------


def test_actor_state_level_defaults_to_unknown():
    actor = ActorState()
    assert actor.level is None


@pytest.mark.parametrize("level", [MIN_LEVEL, 6, 10, MAX_LEVEL])
def test_actor_state_accepts_valid_levels(level):
    actor = ActorState(level=level)
    assert actor.level == level


@pytest.mark.parametrize("level", [MIN_LEVEL - 1, 0, -1, MAX_LEVEL + 1, 19, 100])
def test_actor_state_rejects_out_of_range_levels(level):
    with pytest.raises(ValueError):
        ActorState(level=level)


@pytest.mark.parametrize("level", [True, False])
def test_actor_state_rejects_bool_level(level):
    """`bool` es subclase de `int` en Python — no debe colarse como nivel."""

    with pytest.raises(TypeError):
        ActorState(level=level)


@pytest.mark.parametrize("level", [6.0, 1.0, 18.0])
def test_actor_state_rejects_float_level_even_if_integral(level):
    with pytest.raises(TypeError):
        ActorState(level=level)


@pytest.mark.parametrize("level", ["6", "unknown", ""])
def test_actor_state_rejects_string_level(level):
    with pytest.raises(TypeError):
        ActorState(level=level)


# --- clave ausente / unknown / cero conocido --------------------------------


def test_absent_key_means_mechanic_does_not_exist():
    """Un actor sin ninguna reserva bancada simplemente no puebla la
    clave — no es lo mismo que declarar una reserva en UNKNOWN."""

    actor = ActorState()
    assert "potential_shield_equivalent" not in actor.reserves
    assert actor.reserves.get("potential_shield_equivalent") is None


def test_present_key_with_unknown_means_mechanic_exists_but_unobserved():
    actor = ActorState(reserves={"generic_reserve": ReserveBand.UNKNOWN})
    assert "generic_reserve" in actor.reserves
    assert actor.reserves["generic_reserve"] is ReserveBand.UNKNOWN


def test_present_key_with_known_zero_differs_from_unknown():
    known_empty = ActorState(reserves={"generic_reserve": ReserveBand.NONE})
    unknown = ActorState(reserves={"generic_reserve": ReserveBand.UNKNOWN})

    assert known_empty.reserves["generic_reserve"] is ReserveBand.NONE
    assert unknown.reserves["generic_reserve"] is ReserveBand.UNKNOWN
    assert known_empty.reserves["generic_reserve"] != unknown.reserves["generic_reserve"]


def test_stack_state_distinguishes_absent_unknown_zero_and_concrete():
    absent = ActorState()  # sin ninguna mecánica de stacking declarada
    unknown_mechanic = ActorState(stacks={"generic_mechanic": StackState()})
    known_zero = ActorState(
        stacks={"generic_mechanic": StackState(count=0, window=StackWindow.ACTIVE)}
    )
    concrete = ActorState(
        stacks={"generic_mechanic": StackState(count=3, window=StackWindow.ACTIVE)}
    )

    assert "generic_mechanic" not in absent.stacks
    assert unknown_mechanic.stacks["generic_mechanic"].count is None
    assert known_zero.stacks["generic_mechanic"].count == 0
    assert concrete.stacks["generic_mechanic"].count == 3
    assert known_zero.stacks["generic_mechanic"] != unknown_mechanic.stacks["generic_mechanic"]


# --- StackState: ventana, recompensa, invariantes ---------------------------


def test_stack_state_active_window_with_positive_count():
    stack = StackState(count=3, window=StackWindow.ACTIVE)
    assert stack.count == 3
    assert stack.window is StackWindow.ACTIVE


def test_stack_state_reward_can_be_active_alongside_count():
    stack = StackState(count=5, window=StackWindow.ACTIVE, reward_state=RewardState.ACTIVE)
    assert stack.reward_state is RewardState.ACTIVE


def test_stack_state_reward_state_independent_of_window():
    """Esta etapa no impone ninguna relación obligatoria entre `window` y
    `reward_state`: una recompensa podría tener persistencia distinta de
    su conjunto de cargas, y esa relación debe salir de un hecho mecánico
    futuro, no de una regla genérica de este tipo."""

    StackState(count=2, window=StackWindow.ACTIVE, reward_state=RewardState.UNKNOWN)
    StackState(count=2, window=StackWindow.ACTIVE, reward_state=RewardState.INACTIVE)
    StackState(count=2, window=StackWindow.ACTIVE, reward_state=RewardState.ACTIVE)


def test_stack_state_expired_requires_zero_count():
    stack = StackState(count=0, window=StackWindow.EXPIRED)
    assert stack.window is StackWindow.EXPIRED
    assert stack.count == 0


def test_stack_state_rejects_expired_with_residual_count():
    with pytest.raises(ValueError):
        StackState(count=3, window=StackWindow.EXPIRED)


def test_stack_state_rejects_expired_with_unknown_count():
    """Una ventana expirada exige un cero CONOCIDO, no `None`."""

    with pytest.raises(ValueError):
        StackState(count=None, window=StackWindow.EXPIRED)


def test_stack_state_rejects_negative_count():
    with pytest.raises(ValueError):
        StackState(count=-1, window=StackWindow.ACTIVE)


@pytest.mark.parametrize("count", [True, False])
def test_stack_state_rejects_bool_count(count):
    with pytest.raises(TypeError):
        StackState(count=count, window=StackWindow.ACTIVE)


@pytest.mark.parametrize("count", [3.0, 0.0])
def test_stack_state_rejects_float_count(count):
    with pytest.raises(TypeError):
        StackState(count=count, window=StackWindow.ACTIVE)


def test_stack_state_rejects_string_count():
    with pytest.raises(TypeError):
        StackState(count="3", window=StackWindow.ACTIVE)


def test_stack_state_rejects_raw_string_for_window():
    """Un string crudo que coincide con el VALOR de un miembro del enum
    (p. ej. "expired") no es una instancia del enum — debe rechazarse."""

    with pytest.raises(TypeError):
        StackState(count=3, window="expired")  # type: ignore[arg-type]


def test_stack_state_rejects_raw_string_for_reward_state():
    with pytest.raises(TypeError):
        StackState(count=3, window=StackWindow.ACTIVE, reward_state="active")  # type: ignore[arg-type]


def test_new_cycle_after_expiration_is_a_fresh_independent_stack_state():
    """Una aplicación posterior a una expiración no "continúa" el conteo
    anterior: es un ciclo nuevo, representable como un `StackState`
    independiente sin memoria del ciclo previo."""

    expired = StackState(count=0, window=StackWindow.EXPIRED)
    reapplied = StackState(count=1, window=StackWindow.ACTIVE)

    assert expired.window is StackWindow.EXPIRED
    assert reapplied.window is StackWindow.ACTIVE
    assert reapplied.count == 1
    assert reapplied != expired


# --- ActionContext por acción ------------------------------------------------


def test_two_actions_of_the_same_actor_have_independent_contexts():
    melee_auto = ActionContext(action_ref="basic_attack", range_status=RangeStatus.IN_RANGE)
    long_range_ability = ActionContext(action_ref="long_range_ability", range_status=RangeStatus.OUT_OF_RANGE)
    shared = SharedContext(
        action_contexts={
            melee_auto.action_ref: melee_auto,
            long_range_ability.action_ref: long_range_ability,
        }
    )

    assert shared.action_contexts["basic_attack"].range_status is RangeStatus.IN_RANGE
    assert shared.action_contexts["long_range_ability"].range_status is RangeStatus.OUT_OF_RANGE


def test_isolated_and_contested_actions_coexist_under_the_same_wave_state():
    """La oleada presente no determina el aislamiento de cada acción por
    sí sola — dos acciones pueden declarar valores distintos bajo el
    mismo `wave_state`."""

    isolated_action = ActionContext(action_ref="isolated_ability", target_isolation=IsolationStatus.ISOLATED)
    contested_action = ActionContext(action_ref="contested_ability", target_isolation=IsolationStatus.CONTESTED)
    shared = SharedContext(
        wave_state=WaveState(state=WaveStateKind.PRESENT_NEUTRAL),
        action_contexts={
            isolated_action.action_ref: isolated_action,
            contested_action.action_ref: contested_action,
        },
    )

    assert shared.wave_state.state is WaveStateKind.PRESENT_NEUTRAL
    assert shared.action_contexts["isolated_ability"].target_isolation is IsolationStatus.ISOLATED
    assert shared.action_contexts["contested_ability"].target_isolation is IsolationStatus.CONTESTED


@pytest.mark.parametrize("action_ref", ["", "   ", "\t\n"])
def test_action_context_rejects_empty_or_whitespace_action_ref(action_ref):
    with pytest.raises(ValueError):
        ActionContext(action_ref=action_ref)


def test_action_context_rejects_raw_string_for_range_status():
    with pytest.raises(TypeError):
        ActionContext(action_ref="some_ability", range_status="in_range")  # type: ignore[arg-type]


def test_action_context_rejects_raw_string_for_target_isolation():
    with pytest.raises(TypeError):
        ActionContext(action_ref="some_ability", target_isolation="isolated")  # type: ignore[arg-type]


# --- coherencia clave/action_ref en SharedContext.action_contexts ----------


def test_shared_context_rejects_key_mismatched_with_action_ref():
    with pytest.raises(ValueError):
        SharedContext(action_contexts={"candidate:q": ActionContext(action_ref="candidate:e")})


def test_shared_context_rejects_non_action_context_values():
    with pytest.raises(TypeError):
        SharedContext(action_contexts={"candidate:q": "not an action context"})  # type: ignore[dict-item]


# --- invalidadores: unknown / present / absent ------------------------------


def test_invalidators_support_all_three_states_independently():
    action = ActionContext(
        action_ref="point_and_click_ability",
        invalidators={
            "target_untargetable": InvalidatorStatus.ABSENT,
            "target_out_of_vision": InvalidatorStatus.PRESENT,
            "target_immune": InvalidatorStatus.UNKNOWN,
        },
    )

    assert action.invalidators["target_untargetable"] is InvalidatorStatus.ABSENT
    assert action.invalidators["target_out_of_vision"] is InvalidatorStatus.PRESENT
    assert action.invalidators["target_immune"] is InvalidatorStatus.UNKNOWN


def test_undeclared_invalidator_is_absent_key_not_absent_status():
    action = ActionContext(action_ref="point_and_click_ability", invalidators={})
    assert "some_invalidator" not in action.invalidators
    assert action.invalidators.get("some_invalidator") is None


def test_invalidators_reject_raw_string_values():
    with pytest.raises(TypeError):
        ActionContext(action_ref="point_and_click_ability", invalidators={"target_immune": "present"})


# --- WaveState: combinaciones válidas e inválidas ---------------------------


@pytest.mark.parametrize(
    ("state", "pushing_toward"),
    [
        (WaveStateKind.UNKNOWN, PushDirection.UNKNOWN),
        (WaveStateKind.ABSENT, PushDirection.UNKNOWN),
        (WaveStateKind.PRESENT_NEUTRAL, PushDirection.UNKNOWN),
        (WaveStateKind.PUSHING, PushDirection.CANDIDATE),
        (WaveStateKind.PUSHING, PushDirection.ENEMY),
    ],
)
def test_wave_state_accepts_valid_combinations(state, pushing_toward):
    wave = WaveState(state=state, pushing_toward=pushing_toward)
    assert wave.state is state
    assert wave.pushing_toward is pushing_toward


@pytest.mark.parametrize(
    ("state", "pushing_toward"),
    [
        (WaveStateKind.PUSHING, PushDirection.UNKNOWN),
        (WaveStateKind.UNKNOWN, PushDirection.CANDIDATE),
        (WaveStateKind.UNKNOWN, PushDirection.ENEMY),
        (WaveStateKind.ABSENT, PushDirection.CANDIDATE),
        (WaveStateKind.ABSENT, PushDirection.ENEMY),
        (WaveStateKind.PRESENT_NEUTRAL, PushDirection.CANDIDATE),
        (WaveStateKind.PRESENT_NEUTRAL, PushDirection.ENEMY),
    ],
)
def test_wave_state_rejects_invalid_combinations(state, pushing_toward):
    with pytest.raises(ValueError):
        WaveState(state=state, pushing_toward=pushing_toward)


def test_wave_state_rejects_raw_strings():
    with pytest.raises(TypeError):
        WaveState(state="pushing", pushing_toward=PushDirection.CANDIDATE)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        WaveState(state=WaveStateKind.PUSHING, pushing_toward="candidate")  # type: ignore[arg-type]


# --- AbilityState: rango + disponibilidad -----------------------------------


def test_ability_state_defaults_to_fully_unknown():
    ability = AbilityState()
    assert ability.rank is None
    assert ability.availability is AbilityAvailability.UNKNOWN


def test_ability_state_unlearned_is_rank_zero():
    ability = AbilityState(rank=0, availability=AbilityAvailability.UNLEARNED)
    assert ability.rank == 0
    assert ability.availability is AbilityAvailability.UNLEARNED


def test_ability_state_learned_and_ready():
    ability = AbilityState(rank=3, availability=AbilityAvailability.READY)
    assert ability.rank == 3
    assert ability.availability is AbilityAvailability.READY


def test_ability_state_learned_and_on_cooldown():
    ability = AbilityState(rank=1, availability=AbilityAvailability.ON_COOLDOWN)
    assert ability.rank == 1
    assert ability.availability is AbilityAvailability.ON_COOLDOWN


@pytest.mark.parametrize("rank", [-1, -5])
def test_ability_state_rejects_negative_rank(rank):
    with pytest.raises(ValueError):
        AbilityState(rank=rank, availability=AbilityAvailability.READY)


@pytest.mark.parametrize("rank", [True, False])
def test_ability_state_rejects_bool_rank(rank):
    with pytest.raises(TypeError):
        AbilityState(rank=rank)


def test_ability_state_rejects_float_rank():
    with pytest.raises(TypeError):
        AbilityState(rank=2.0)


def test_ability_state_rejects_string_rank():
    with pytest.raises(TypeError):
        AbilityState(rank="2")


def test_ability_state_rejects_zero_rank_with_ready_or_on_cooldown():
    with pytest.raises(ValueError):
        AbilityState(rank=0, availability=AbilityAvailability.READY)
    with pytest.raises(ValueError):
        AbilityState(rank=0, availability=AbilityAvailability.ON_COOLDOWN)


def test_ability_state_rejects_positive_rank_with_unlearned():
    with pytest.raises(ValueError):
        AbilityState(rank=1, availability=AbilityAvailability.UNLEARNED)
    with pytest.raises(ValueError):
        AbilityState(rank=5, availability=AbilityAvailability.UNLEARNED)


def test_ability_state_rejects_raw_string_availability():
    with pytest.raises(TypeError):
        AbilityState(rank=1, availability="ready")  # type: ignore[arg-type]


def test_two_abilities_of_the_same_actor_can_have_different_ranks():
    actor = ActorState(
        abilities={
            "slot_a": AbilityState(rank=1, availability=AbilityAvailability.READY),
            "slot_b": AbilityState(rank=3, availability=AbilityAvailability.ON_COOLDOWN),
        }
    )
    assert actor.abilities["slot_a"].rank == 1
    assert actor.abilities["slot_b"].rank == 3
    assert actor.abilities["slot_a"] != actor.abilities["slot_b"]


def test_actor_state_abilities_reject_wrong_value_type():
    with pytest.raises(TypeError):
        ActorState(abilities={"slot_a": AbilityAvailability.READY})  # type: ignore[dict-item]


# --- coherencia de recursos: RESOURCELESS -----------------------------------


@pytest.mark.parametrize("band", [ResourceBand.FULL, ResourceBand.PARTIAL])
def test_resourceless_rejects_full_or_partial_band(band):
    with pytest.raises(ValueError):
        ActorState(resource_type=ResourceKind.RESOURCELESS, resource_band=band)


def test_resourceless_accepts_none_band():
    actor = ActorState(resource_type=ResourceKind.RESOURCELESS, resource_band=ResourceBand.NONE)
    assert actor.resource_band is ResourceBand.NONE


def test_resourceless_accepts_unknown_band():
    """Un tipo o banda UNKNOWN puede ser legítimo mientras todavía no
    exista información suficiente — no se sobrevalida."""

    actor = ActorState(resource_type=ResourceKind.RESOURCELESS, resource_band=ResourceBand.UNKNOWN)
    assert actor.resource_band is ResourceBand.UNKNOWN


def test_unknown_resource_type_does_not_constrain_band():
    for band in ResourceBand:
        ActorState(resource_type=ResourceKind.UNKNOWN, resource_band=band)


def test_mana_resource_accepts_full_or_partial_band():
    ActorState(resource_type=ResourceKind.MANA, resource_band=ResourceBand.FULL)
    ActorState(resource_type=ResourceKind.MANA, resource_band=ResourceBand.PARTIAL)


# --- inmutabilidad real: mappings congelados --------------------------------


def test_actor_state_stacks_mapping_is_frozen():
    actor = ActorState(stacks={"m": StackState(count=1, window=StackWindow.ACTIVE)})
    assert isinstance(actor.stacks, MappingProxyType)
    with pytest.raises(TypeError):
        actor.stacks["m"] = StackState(count=99, window=StackWindow.ACTIVE)  # type: ignore[index]
    with pytest.raises(TypeError):
        del actor.stacks["m"]  # type: ignore[attr-defined]


def test_actor_state_reserves_mapping_is_frozen():
    actor = ActorState(reserves={"r": ReserveBand.PARTIAL})
    with pytest.raises(TypeError):
        actor.reserves["r"] = ReserveBand.NEAR_MAX  # type: ignore[index]


def test_actor_state_abilities_mapping_is_frozen():
    actor = ActorState(abilities={"slot_a": AbilityState(rank=1, availability=AbilityAvailability.READY)})
    with pytest.raises(TypeError):
        actor.abilities["slot_a"] = AbilityState()  # type: ignore[index]


def test_actor_state_extension_mapping_is_frozen():
    actor = ActorState(extension={"barrel:count": "2"})
    with pytest.raises(TypeError):
        actor.extension["barrel:count"] = "3"  # type: ignore[index]


def test_action_context_invalidators_mapping_is_frozen():
    action = ActionContext(action_ref="a", invalidators={"x": InvalidatorStatus.ABSENT})
    with pytest.raises(TypeError):
        action.invalidators["x"] = InvalidatorStatus.PRESENT  # type: ignore[index]


def test_shared_context_action_contexts_mapping_is_frozen():
    ctx = ActionContext(action_ref="a")
    shared = SharedContext(action_contexts={"a": ctx})
    with pytest.raises(TypeError):
        shared.action_contexts["a"] = ActionContext(action_ref="a")  # type: ignore[index]


def test_mutating_original_dict_after_construction_does_not_affect_snapshot():
    """Copia defensiva: un `dict` externo mutado después de construir el
    estado no debe alterar retroactivamente el snapshot ya construido."""

    original_stacks = {"m": StackState(count=1, window=StackWindow.ACTIVE)}
    actor = ActorState(stacks=original_stacks)

    original_stacks["m"] = StackState(count=99, window=StackWindow.ACTIVE)
    original_stacks["new_key"] = StackState(count=5, window=StackWindow.ACTIVE)

    assert actor.stacks["m"].count == 1
    assert "new_key" not in actor.stacks


def test_mutating_original_action_contexts_dict_does_not_affect_snapshot():
    original = {"a": ActionContext(action_ref="a", range_status=RangeStatus.IN_RANGE)}
    shared = SharedContext(action_contexts=original)

    original["a"] = ActionContext(action_ref="a", range_status=RangeStatus.OUT_OF_RANGE)

    assert shared.action_contexts["a"].range_status is RangeStatus.IN_RANGE


# --- microfix de cierre de Etapa 1: claves de mapping no-string/vacías -------

_VALID_VALUE_BY_ACTOR_FIELD = {
    "stacks": StackState(count=1, window=StackWindow.ACTIVE),
    "reserves": ReserveBand.NONE,
    "abilities": AbilityState(rank=1, availability=AbilityAvailability.READY),
    "extension": "some_qualitative_value",
}


@pytest.mark.parametrize("field_name", ["stacks", "reserves", "abilities", "extension"])
@pytest.mark.parametrize("bad_key", [123, True, False, None, 1.5])
def test_actor_state_mapping_rejects_non_string_keys(field_name, bad_key):
    value = _VALID_VALUE_BY_ACTOR_FIELD[field_name]

    with pytest.raises(TypeError):
        ActorState(**{field_name: {bad_key: value}})


@pytest.mark.parametrize("field_name", ["stacks", "reserves", "abilities", "extension"])
@pytest.mark.parametrize("bad_key", ["", "   ", "\t\n"])
def test_actor_state_mapping_rejects_empty_or_whitespace_keys(field_name, bad_key):
    value = _VALID_VALUE_BY_ACTOR_FIELD[field_name]

    with pytest.raises(ValueError):
        ActorState(**{field_name: {bad_key: value}})


@pytest.mark.parametrize("bad_key", [123, True, None])
def test_action_context_invalidators_rejects_non_string_keys(bad_key):
    with pytest.raises(TypeError):
        ActionContext(action_ref="candidate:q", invalidators={bad_key: InvalidatorStatus.PRESENT})


@pytest.mark.parametrize("bad_key", ["", "   "])
def test_action_context_invalidators_rejects_empty_or_whitespace_keys(bad_key):
    with pytest.raises(ValueError):
        ActionContext(action_ref="candidate:q", invalidators={bad_key: InvalidatorStatus.PRESENT})


@pytest.mark.parametrize("bad_key", [123, True, None])
def test_shared_context_action_contexts_rejects_non_string_keys(bad_key):
    with pytest.raises(TypeError):
        SharedContext(action_contexts={bad_key: ActionContext(action_ref="candidate:q")})


@pytest.mark.parametrize("bad_key", ["", "   "])
def test_shared_context_action_contexts_rejects_empty_or_whitespace_keys(bad_key):
    # la clave vacía/whitespace se rechaza antes de siquiera comparar contra
    # action_ref — no importa que el ActionContext en sí sea válido.
    with pytest.raises(ValueError):
        SharedContext(action_contexts={bad_key: ActionContext(action_ref="candidate:q")})


def test_actor_state_stacks_preserves_valid_key_without_normalization():
    key = "  candidate:hemorrhage  "  # espacios internos/laterales, no solo-espacios

    state = ActorState(stacks={key: StackState(count=2, window=StackWindow.ACTIVE)})

    assert list(state.stacks.keys()) == [key]
    assert state.stacks[key].count == 2


def test_shared_context_action_contexts_preserves_valid_key_without_normalization():
    key = "candidate:q "
    context = ActionContext(action_ref=key)

    shared = SharedContext(action_contexts={key: context})

    assert list(shared.action_contexts.keys()) == [key]


def test_action_context_action_ref_wrong_type_raises_type_error():
    with pytest.raises(TypeError):
        ActionContext(action_ref=123)


def test_action_context_action_ref_empty_string_raises_value_error():
    with pytest.raises(ValueError):
        ActionContext(action_ref="   ")


# --- microfix de cierre de Etapa 1: frontera de serialización explícita -----


def _build_nontrivial_combat_state() -> CombatState:
    candidate = ActorState(
        level=6,
        health_band=HealthBand.HIGH,
        resource_type=ResourceKind.MANA,
        resource_band=ResourceBand.PARTIAL,
        stacks={
            "hemorrhage": StackState(count=3, window=StackWindow.ACTIVE, reward_state=RewardState.INACTIVE),
        },
        reserves={"shield": ReserveBand.NONE},
        abilities={
            "q": AbilityState(rank=3, availability=AbilityAvailability.READY),
            "r": AbilityState(rank=0, availability=AbilityAvailability.UNLEARNED),
        },
        extension={"zone:count": "2"},
    )
    enemy = ActorState()  # todo lo dejado en default: unknown/ausente
    shared = SharedContext(
        wave_state=WaveState(state=WaveStateKind.PUSHING, pushing_toward=PushDirection.CANDIDATE),
        action_contexts={
            "candidate:q": ActionContext(
                action_ref="candidate:q",
                range_status=RangeStatus.IN_RANGE,
                invalidators={"cc": InvalidatorStatus.ABSENT},
            ),
        },
    )
    return CombatState(candidate=candidate, enemy=enemy, shared=shared)


def test_combat_state_to_primitive_converts_full_snapshot():
    primitive = combat_state_to_primitive(_build_nontrivial_combat_state())

    assert primitive["candidate"]["level"] == 6
    assert primitive["candidate"]["health_band"] == "high"
    assert primitive["candidate"]["stacks"]["hemorrhage"]["count"] == 3
    assert primitive["candidate"]["abilities"]["r"]["availability"] == "unlearned"
    assert primitive["shared"]["wave_state"]["pushing_toward"] == "candidate"
    assert primitive["shared"]["action_contexts"]["candidate:q"]["invalidators"]["cc"] == "absent"


def test_combat_state_to_primitive_converts_enums_to_their_string_values():
    primitive = combat_state_to_primitive(_build_nontrivial_combat_state())

    assert primitive["candidate"]["resource_type"] == "mana"
    assert primitive["candidate"]["resource_band"] == "partial"
    assert primitive["candidate"]["stacks"]["hemorrhage"]["window"] == "active"
    assert primitive["shared"]["wave_state"]["state"] == "pushing"
    assert primitive["shared"]["action_contexts"]["candidate:q"]["range_status"] == "in_range"


def test_combat_state_to_primitive_preserves_absent_key_unknown_and_known_zero():
    primitive = combat_state_to_primitive(_build_nontrivial_combat_state())

    # clave ausente: el enemigo no declaró ninguna entrada de stacks/reserves
    assert primitive["enemy"]["stacks"] == {}
    assert primitive["enemy"]["reserves"] == {}
    # escalar sin declarar -> "unknown" explícito, no se omite el campo
    assert primitive["enemy"]["health_band"] == "unknown"
    # None real para un nivel desconocido
    assert primitive["enemy"]["level"] is None
    # cero conocido preservado como 0, nunca como None ni omitido
    assert primitive["candidate"]["abilities"]["r"]["rank"] == 0


def test_combat_state_to_primitive_is_json_serializable():
    primitive = combat_state_to_primitive(_build_nontrivial_combat_state())

    serialized = json.dumps(primitive)

    assert json.loads(serialized) == primitive


def test_combat_state_to_primitive_uses_only_json_primitive_types():
    def _assert_all_primitive(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert isinstance(key, str)
                _assert_all_primitive(value)
        elif isinstance(node, list):
            for item in node:
                _assert_all_primitive(item)
        else:
            assert node is None or isinstance(node, (str, int, bool))

    _assert_all_primitive(combat_state_to_primitive(_build_nontrivial_combat_state()))


def test_mutating_serialized_dict_does_not_affect_snapshot():
    state = _build_nontrivial_combat_state()
    primitive = combat_state_to_primitive(state)

    primitive["candidate"]["stacks"]["hemorrhage"]["count"] = 999
    primitive["candidate"]["abilities"]["q"] = {"rank": 99, "availability": "ready"}
    del primitive["shared"]["action_contexts"]["candidate:q"]

    assert state.candidate.stacks["hemorrhage"].count == 3
    assert state.candidate.abilities["q"].rank == 3
    assert "candidate:q" in state.shared.action_contexts


def test_serializing_does_not_mutate_original_state():
    state = _build_nontrivial_combat_state()

    combat_state_to_primitive(state)

    assert isinstance(state.candidate.stacks, MappingProxyType)
    assert isinstance(state.shared.action_contexts, MappingProxyType)
    assert state.candidate.stacks["hemorrhage"].count == 3


def test_combat_state_to_primitive_is_deterministic_for_equivalent_snapshots():
    state_a = _build_nontrivial_combat_state()
    state_b = _build_nontrivial_combat_state()

    assert combat_state_to_primitive(state_a) == combat_state_to_primitive(state_b)


def test_combat_state_to_primitive_rejects_wrong_type():
    with pytest.raises(TypeError):
        combat_state_to_primitive("not a combat state")  # type: ignore[arg-type]


# --- ausencia de nombres de campeones/habilidades/matchups ------------------

_FORBIDDEN_SUBSTRINGS = (
    "darius",
    "mordekaiser",
    "hemorrhage",
    "noxian",
    "decimate",
    "apprehend",
    "crippling",
    "obliterate",
    "indestructible",
    "death's_grasp",
    "deaths_grasp",
    "realm_of_death",
    "potential_shield",
    "darkness_rise",
)


def _all_declared_names(*types: type) -> set[str]:
    names: set[str] = set()
    for t in types:
        names.add(t.__name__)
        if issubclass(t, Enum):
            for member in t:
                names.add(member.name)
                names.add(str(member.value))
        if dataclasses.is_dataclass(t):
            for f in dataclasses.fields(t):
                names.add(f.name)
    return names


def test_no_champion_or_ability_specific_names_anywhere_in_the_model():
    types = (
        CombatState,
        ActorState,
        SharedContext,
        ActionContext,
        StackState,
        WaveState,
        AbilityState,
        HealthBand,
        ResourceKind,
        ResourceBand,
        ReserveBand,
        AbilityAvailability,
        StackWindow,
        RewardState,
        RangeStatus,
        IsolationStatus,
        InvalidatorStatus,
        WaveStateKind,
        PushDirection,
    )
    declared = {name.lower() for name in _all_declared_names(*types)}

    offending = {
        forbidden
        for forbidden in _FORBIDDEN_SUBSTRINGS
        for name in declared
        if forbidden in name
    }
    assert not offending, f"nombres específicos de campeón/habilidad filtrados al modelo genérico: {offending}"
