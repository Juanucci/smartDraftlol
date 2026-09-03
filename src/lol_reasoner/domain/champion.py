"""Representación semántica de un campeón.

Estos dataclasses son el contrato entre la base de conocimiento (YAML) y
el motor de razonamiento. No modelan stats numéricos reales de LoL: son
una representación cualitativa pensada para que las reglas puedan operar
sobre estructura (ejes, efectos, mecánicas de acumulación), no sobre
nombres de campeón ni sobre afirmaciones de resultado precargadas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from lol_reasoner.domain.enums import (
    Axis,
    CooldownClass,
    DamageType,
    EffectCondition,
    EffectType,
    Phase,
    ResourceType,
    TacticalUse,
    TradePattern,
)


@dataclass(frozen=True, slots=True)
class DamageProfile:
    """Mezcla de tipos de daño, puramente descriptiva para la salida humana.

    NINGUNA regla la lee: la fuente de verdad para el razonamiento es
    `Effect.damage_type`, filtrado por fase de disponibilidad de la
    habilidad que lo porta (ver tests/test_dead_fields.py)."""

    physical: float
    magic: float
    true: float


@dataclass(frozen=True, slots=True)
class Effect:
    """Un efecto estructurado de una habilidad. Una `Ability` tiene N."""

    type: EffectType
    magnitude: int  # 0..4
    conditions: frozenset[EffectCondition] = field(default_factory=frozenset)
    damage_type: DamageType | None = None
    # Solo para EffectType.STACK_APPLICATION: id de la StackingMechanic a
    # la que este efecto aporta una aplicación (p. ej. el filo exterior de
    # Decimate alimenta "hemorrhage"). Debe ser consistente con
    # `StackingMechanic.applied_by` (validado cruzadamente en schema.py).
    feeds_stack: str | None = None
    # Solo para efectos cuyo VALOR escala con el conteo actual de una
    # StackingMechanic (p. ej. el daño de Noxian Guillotine escala con
    # las cargas de Hemorrhage ya aplicadas). Es una referencia
    # estructural, no una tasa: el motor no simula el conteo real de
    # cargas durante una partida, solo que la relación existe.
    stack_scaling: str | None = None
    # Solo para efectos AMPLIFY_ABILITY dentro de un `StackReward`: qué
    # slot de habilidad amplifica, para poder filtrar por disponibilidad
    # de fase (p. ej. Noxian Might amplifica R, disponible desde level_6).
    amplifies_slot: str | None = None
    # Por defecto, CUALQUIER daño (incluido el verdadero) es absorbible
    # por un escudo genérico: ver ShieldAbsorbsAnyDamageRule. Este flag
    # existe para que una habilidad FUTURA y concreta pueda declarar
    # explícitamente que ignora escudos — nunca se infiere del
    # damage_type, y ninguna habilidad de este hito lo activa.
    bypasses_shields: bool = False
    doc: str = ""  # documentación humana; ninguna regla la lee (test lo exige)

    def has_condition(self, condition: EffectCondition) -> bool:
        return condition in self.conditions


@dataclass(frozen=True, slots=True)
class Ability:
    slot: str  # "P" | "Q" | "W" | "E" | "R"
    name: str
    cooldown_class: CooldownClass
    effects: tuple[Effect, ...]
    tactical_uses: frozenset[TacticalUse] = field(default_factory=frozenset)
    available_from: Phase = Phase.EARLY_LANE
    doc: str = ""  # documentación humana; ninguna regla la lee (test lo exige)

    def effect_types(self) -> frozenset[EffectType]:
        return frozenset(e.type for e in self.effects)

    def effects_of(self, effect_type: EffectType) -> tuple[Effect, ...]:
        return tuple(e for e in self.effects if e.type == effect_type)


@dataclass(frozen=True, slots=True)
class StackingMechanic:
    """Mecánica de acumulación genérica: umbral, fuentes y recompensa.

    Representa tanto Hemorrhage (5 cargas, recompensa tardía y grande)
    como Darkness Rise (3 impactos, recompensa temprana y menor) con la
    misma estructura, sin nombrar a ningún campeón. La velocidad de
    acumulación NO se declara acá: se deriva estructuralmente en
    `reasoning/rules/stacking.py` a partir de `applied_by` y de qué
    habilidades tienen efectos `AUTO_ATTACK_RESET`/`EMPOWER_NEXT_ATTACK`.
    """

    id: str
    name: str
    threshold: int
    stacks_per_application: int
    applied_by: frozenset[str]  # slots de habilidad, o el token "basic_attack"
    reward_name: str
    reward_effects: tuple[Effect, ...] = field(default_factory=tuple)

    @property
    def applications_needed(self) -> int:
        return ceil(self.threshold / self.stacks_per_application)


@dataclass(frozen=True, slots=True)
class PowerSpike:
    phase: Phase
    magnitude: int  # 0..4
    reason: str


@dataclass(frozen=True, slots=True)
class Champion:
    id: str
    name: str
    archetype: str
    damage_profile: DamageProfile  # descriptivo; ver docstring de DamageProfile
    axes: dict[Axis, int]
    casting_resource: ResourceType
    trade_patterns: frozenset[TradePattern]  # descriptivo; ver docstring de TradePattern
    tags: frozenset[str]  # vacío en este hito; ver domain/enums.py
    abilities: tuple[Ability, ...]
    stacking_mechanics: tuple[StackingMechanic, ...]
    spikes: tuple[PowerSpike, ...]
    knowledge_version: str

    def axis(self, axis: Axis) -> int:
        return self.axes[axis]

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    def ability(self, slot: str) -> Ability | None:
        return next((a for a in self.abilities if a.slot == slot), None)
