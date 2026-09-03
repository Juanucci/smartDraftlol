"""Representación semántica de un campeón.

Estos dataclasses son el contrato entre la base de conocimiento (YAML) y
el motor de razonamiento. No modelan stats numéricos reales de LoL: son
una representación cualitativa pensada para que las reglas puedan operar
sobre ejes y tags, no sobre nombres de campeón.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lol_reasoner.domain.enums import Axis, CooldownClass, EffectKind, Phase, TradePattern


@dataclass(frozen=True, slots=True)
class DamageProfile:
    """Mezcla de tipos de daño, como fracciones que orientativamente suman ~1.0.

    No es un cálculo real de daño mitigado; es una señal para reglas del
    tipo "el daño mágico/verdadero conserva valor contra la armadura".
    """

    physical: float
    magic: float
    true: float


@dataclass(frozen=True, slots=True)
class AbilityEffect:
    """Efecto de una habilidad relevante para el razonamiento.

    `counters`/`countered_by` son tags (no nombres de habilidad rival):
    esto es lo que permite que una regla general del tipo "una habilidad
    defensiva puede negar un patrón rival" se aplique sin conocer los
    kits específicos que se enfrentan.
    """

    slot: str  # "P" | "Q" | "W" | "E" | "R"
    name: str
    kind: EffectKind
    cooldown_class: CooldownClass
    counters: frozenset[str] = field(default_factory=frozenset)
    countered_by: frozenset[str] = field(default_factory=frozenset)
    available_from: Phase = Phase.EARLY_LANE
    note: str = ""


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
    damage_profile: DamageProfile
    axes: dict[Axis, int]
    trade_pattern: TradePattern
    tags: frozenset[str]
    abilities: tuple[AbilityEffect, ...]
    spikes: tuple[PowerSpike, ...]
    strengths: tuple[str, ...]
    vulnerabilities: tuple[str, ...]
    knowledge_version: str

    def axis(self, axis: Axis) -> int:
        return self.axes[axis]

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    def abilities_of_kind(self, kind: EffectKind) -> tuple[AbilityEffect, ...]:
        return tuple(a for a in self.abilities if a.kind == kind)
