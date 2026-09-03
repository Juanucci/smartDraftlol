"""Carga de campeones desde YAML hacia `Champion`."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml

from lol_reasoner.domain.champion import AbilityEffect, Champion, DamageProfile, PowerSpike
from lol_reasoner.domain.enums import Axis, CooldownClass, EffectKind, Phase, TradePattern
from lol_reasoner.knowledge.schema import validate_champion_dict


def _build_champion(data: dict) -> Champion:
    damage_profile = DamageProfile(**data["damage_profile"])
    axes = {Axis(name): value for name, value in data["axes"].items()}
    abilities = tuple(
        AbilityEffect(
            slot=a["slot"],
            name=a["name"],
            kind=EffectKind(a["kind"]),
            cooldown_class=CooldownClass(a["cooldown_class"]),
            counters=frozenset(a.get("counters", [])),
            countered_by=frozenset(a.get("countered_by", [])),
            available_from=Phase(a.get("available_from", Phase.EARLY_LANE.value)),
            note=a.get("note", ""),
        )
        for a in data["abilities"]
    )
    spikes = tuple(
        PowerSpike(phase=Phase(s["phase"]), magnitude=s["magnitude"], reason=s["reason"]) for s in data["spikes"]
    )
    return Champion(
        id=data["id"],
        name=data["name"],
        archetype=data["archetype"],
        damage_profile=damage_profile,
        axes=axes,
        trade_pattern=TradePattern(data["trade_pattern"]),
        tags=frozenset(data["tags"]),
        abilities=abilities,
        spikes=spikes,
        strengths=tuple(data["strengths"]),
        vulnerabilities=tuple(data["vulnerabilities"]),
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
