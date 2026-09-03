"""Carga de campeones desde YAML hacia `Champion` — schema v2."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml

from lol_reasoner.domain.champion import Ability, Champion, DamageProfile, Effect, PowerSpike, StackingMechanic
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
from lol_reasoner.knowledge.schema import validate_champion_dict


def _build_effect(e: dict) -> Effect:
    return Effect(
        type=EffectType(e["type"]),
        magnitude=e["magnitude"],
        conditions=frozenset(EffectCondition(c) for c in e.get("conditions", [])),
        damage_type=DamageType(e["damage_type"]) if e.get("damage_type") else None,
        feeds_stack=e.get("feeds_stack"),
        stack_scaling=e.get("stack_scaling"),
        amplifies_slot=e.get("amplifies_slot"),
        bypasses_shields=e.get("bypasses_shields", False),
        doc=e.get("doc", ""),
    )


def _build_ability(a: dict) -> Ability:
    return Ability(
        slot=a["slot"],
        name=a["name"],
        cooldown_class=CooldownClass(a["cooldown_class"]),
        effects=tuple(_build_effect(e) for e in a["effects"]),
        tactical_uses=frozenset(TacticalUse(u) for u in a.get("tactical_uses", [])),
        available_from=Phase(a.get("available_from", Phase.EARLY_LANE.value)),
        doc=a.get("doc", ""),
    )


def _build_stacking_mechanic(m: dict) -> StackingMechanic:
    return StackingMechanic(
        id=m["id"],
        name=m["name"],
        threshold=m["threshold"],
        stacks_per_application=m["stacks_per_application"],
        applied_by=frozenset(m["applied_by"]),
        reward_name=m["reward_name"],
        reward_effects=tuple(_build_effect(e) for e in m.get("reward_effects", [])),
    )


def _build_champion(data: dict) -> Champion:
    damage_profile = DamageProfile(**data["damage_profile"])
    axes = {Axis(name): value for name, value in data["axes"].items()}
    abilities = tuple(_build_ability(a) for a in data["abilities"])
    stacking_mechanics = tuple(_build_stacking_mechanic(m) for m in data["stacking_mechanics"])
    spikes = tuple(
        PowerSpike(phase=Phase(s["phase"]), magnitude=s["magnitude"], reason=s["reason"]) for s in data["spikes"]
    )
    return Champion(
        id=data["id"],
        name=data["name"],
        archetype=data["archetype"],
        damage_profile=damage_profile,
        axes=axes,
        casting_resource=ResourceType(data["casting_resource"]),
        trade_patterns=frozenset(TradePattern(t) for t in data["trade_patterns"]),
        tags=frozenset(data["tags"]),
        abilities=abilities,
        stacking_mechanics=stacking_mechanics,
        spikes=spikes,
        knowledge_version=data["knowledge_version"],
    )


def load_champion_from_dict(data: dict, *, source: str = "<dict>") -> Champion:
    """Valida y construye un `Champion` a partir de un dict ya parseado.

    Expuesto aparte de `load_champion_file` para que los tests
    contrafactuales puedan mutar una copia del dict y reconstruir el
    campeón sin tocar el archivo YAML en disco.
    """

    validate_champion_dict(data, source=source)
    return _build_champion(data)


def load_champion_file(path: Path) -> Champion:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return load_champion_from_dict(data, source=str(path))


def load_all_champions(directory: Path | None = None) -> dict[str, Champion]:
    """Carga todos los YAML de un directorio (por defecto, el paquete embebido)."""

    champions: dict[str, Champion] = {}
    if directory is None:
        champion_files = [p for p in resources.files("lol_reasoner.knowledge.champions").iterdir() if p.name.endswith(".yaml")]
        for resource in sorted(champion_files, key=lambda p: p.name):
            with resources.as_file(resource) as path:
                champ = load_champion_file(path)
                champions[champ.id] = champ
    else:
        for path in sorted(directory.glob("*.yaml")):
            champ = load_champion_file(path)
            champions[champ.id] = champ
    return champions
