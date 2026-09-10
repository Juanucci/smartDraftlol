"""Tests del modelo tipado de estado (v1.7, Etapa 1).

Cubren únicamente el modelo de dominio en `domain/combat_state.py`: su
composición, sus invariantes de construcción, y la distinción entre clave
ausente / valor desconocido / cero conocido / valor concreto. No hay
secuencias, generador de escenarios, invalidadores concretos, daño,
timestamps, ticks, ganador ni score en este archivo — esa es la etapa
siguiente, no esta.
"""

from __future__ import annotations

import dataclasses
from enum import Enum

import pytest

from lol_reasoner.domain.combat_state import (
    MAX_LEVEL,
    MIN_LEVEL,
    ActionContext,
    ActorState,
    AbilityAvailability,
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
    assert state.shared.action_contexts == {}


def test_combat_state_accepts_explicit_shared_context():
    shared = SharedContext(wave_state=WaveState(state=WaveStateKind.PRESENT_NEUTRAL))
    state = CombatState(candidate=ActorState(), enemy=ActorState(), shared=shared)

    assert state.shared.wave_state.state is WaveStateKind.PRESENT_NEUTRAL


def test_combat_state_is_frozen():
    state = CombatState(candidate=ActorState(), enemy=ActorState())
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.candidate = ActorState(level=6)  # type: ignore[misc]


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
    # cero conocido y desconocido no son intercambiables
    assert known_zero.stacks["generic_mechanic"] != unknown_mechanic.stacks["generic_mechanic"]


# --- StackState: ventana, recompensa, invariantes ---------------------------


def test_stack_state_active_window_with_positive_count():
    stack = StackState(count=3, window=StackWindow.ACTIVE)
    assert stack.count == 3
    assert stack.window is StackWindow.ACTIVE


def test_stack_state_reward_can_be_active_alongside_count():
    stack = StackState(count=5, window=StackWindow.ACTIVE, reward_state=RewardState.ACTIVE)
    assert stack.reward_state is RewardState.ACTIVE


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


def test_new_cycle_after_expiration_is_a_fresh_independent_stack_state():
    """Una aplicación posterior a una expiración no "continúa" el conteo
    anterior: es un ciclo nuevo, representable como un `StackState`
    independiente sin memoria del ciclo previo."""

    expired = StackState(count=0, window=StackWindow.EXPIRED)
    reapplied = StackState(count=1, window=StackWindow.ACTIVE)

    assert expired.window is StackWindow.EXPIRED
    assert reapplied.window is StackWindow.ACTIVE
    assert reapplied.count == 1
    # ningún campo de `reapplied` referencia o depende de `expired`
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


def test_action_context_rejects_empty_action_ref():
    with pytest.raises(ValueError):
        ActionContext(action_ref="")


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
    # no existe un valor "ausente por default": la clave simplemente no está
    assert action.invalidators.get("some_invalidator") is None


# --- disponibilidad de habilidades: ready / on_cooldown / unknown ----------


def test_abilities_available_distinguishes_ready_and_on_cooldown():
    actor = ActorState(
        abilities_available={
            "slot_a": AbilityAvailability.READY,
            "slot_b": AbilityAvailability.ON_COOLDOWN,
        }
    )
    assert actor.abilities_available["slot_a"] is AbilityAvailability.READY
    assert actor.abilities_available["slot_b"] is AbilityAvailability.ON_COOLDOWN
    assert "slot_c" not in actor.abilities_available


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
