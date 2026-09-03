"""Validación de la forma esperada de un YAML de campeón.

Deliberadamente manual (sin pydantic ni jsonschema) para mantener la
única dependencia del proyecto en `pyyaml`. Los mensajes de error están
pensados para ser accionables al editar un YAML a mano.
"""

from __future__ import annotations

from lol_reasoner.domain.enums import ALL_AXES, ALL_TAGS, AXIS_MAX, AXIS_MIN, CooldownClass, EffectKind, Phase, TradePattern

REQUIRED_TOP_LEVEL_KEYS = {
    "id",
    "name",
    "archetype",
    "damage_profile",
    "axes",
    "trade_pattern",
    "tags",
    "abilities",
    "spikes",
    "strengths",
    "vulnerabilities",
    "knowledge_version",
}

REQUIRED_AXIS_NAMES = {a.value for a in ALL_AXES}
VALID_SLOTS = {"P", "Q", "W", "E", "R"}
VALID_PHASES = {p.value for p in Phase}
VALID_EFFECT_KINDS = {k.value for k in EffectKind}
VALID_COOLDOWN_CLASSES = {c.value for c in CooldownClass}
VALID_TRADE_PATTERNS = {t.value for t in TradePattern}


class KnowledgeError(ValueError):
    """Error de validación de un archivo de la base de conocimiento."""


def validate_champion_dict(data: dict, *, source: str) -> None:
    missing = REQUIRED_TOP_LEVEL_KEYS - data.keys()
    if missing:
        raise KnowledgeError(f"{source}: faltan claves obligatorias: {sorted(missing)}")

    _validate_damage_profile(data["damage_profile"], source)
    _validate_axes(data["axes"], source)

    if data["trade_pattern"] not in VALID_TRADE_PATTERNS:
        raise KnowledgeError(f"{source}: trade_pattern inválido '{data['trade_pattern']}', esperado uno de {sorted(VALID_TRADE_PATTERNS)}")

    unknown_tags = set(data["tags"]) - ALL_TAGS
    if unknown_tags:
        raise KnowledgeError(f"{source}: tags desconocidos {sorted(unknown_tags)}, ver domain/enums.py:Tag")

    if not isinstance(data["abilities"], list) or not data["abilities"]:
        raise KnowledgeError(f"{source}: 'abilities' debe ser una lista no vacía")
    for ability in data["abilities"]:
        _validate_ability(ability, source)

    if not isinstance(data["spikes"], list):
        raise KnowledgeError(f"{source}: 'spikes' debe ser una lista")
    for spike in data["spikes"]:
        _validate_spike(spike, source)

    for key in ("strengths", "vulnerabilities"):
        if not isinstance(data[key], list) or not all(isinstance(s, str) for s in data[key]):
            raise KnowledgeError(f"{source}: '{key}' debe ser una lista de strings")

    if not isinstance(data["knowledge_version"], str):
        raise KnowledgeError(f"{source}: 'knowledge_version' debe ser string (versión interna de la KB, no un parche de LoL)")


def _validate_damage_profile(profile: dict, source: str) -> None:
    required = {"physical", "magic", "true"}
    if not isinstance(profile, dict) or set(profile.keys()) != required:
        raise KnowledgeError(f"{source}: damage_profile debe tener exactamente las claves {sorted(required)}")
    total = sum(profile.values())
    if not (0.9 <= total <= 1.1):
        raise KnowledgeError(f"{source}: damage_profile debe sumar ~1.0 (suma actual: {total})")
    for k, v in profile.items():
        if not (0.0 <= v <= 1.0):
            raise KnowledgeError(f"{source}: damage_profile.{k}={v} fuera de rango [0,1]")


def _validate_axes(axes: dict, source: str) -> None:
    if not isinstance(axes, dict):
        raise KnowledgeError(f"{source}: 'axes' debe ser un mapa")
    missing = REQUIRED_AXIS_NAMES - axes.keys()
    if missing:
        raise KnowledgeError(f"{source}: faltan ejes {sorted(missing)}")
    extra = axes.keys() - REQUIRED_AXIS_NAMES
    if extra:
        raise KnowledgeError(f"{source}: ejes desconocidos {sorted(extra)}")
    for name, value in axes.items():
        if not isinstance(value, int) or not (AXIS_MIN <= value <= AXIS_MAX):
            raise KnowledgeError(f"{source}: axes.{name}={value!r} debe ser un entero entre {AXIS_MIN} y {AXIS_MAX}")


def _validate_ability(ability: dict, source: str) -> None:
    required = {"slot", "name", "kind", "cooldown_class"}
    missing = required - ability.keys()
    if missing:
        raise KnowledgeError(f"{source}: ability {ability.get('name', '?')} sin claves {sorted(missing)}")
    if ability["slot"] not in VALID_SLOTS:
        raise KnowledgeError(f"{source}: slot inválido '{ability['slot']}'")
    if ability["kind"] not in VALID_EFFECT_KINDS:
        raise KnowledgeError(f"{source}: kind inválido '{ability['kind']}' en {ability['name']}, ver EffectKind")
    if ability["cooldown_class"] not in VALID_COOLDOWN_CLASSES:
        raise KnowledgeError(f"{source}: cooldown_class inválido '{ability['cooldown_class']}' en {ability['name']}")
    for key in ("counters", "countered_by"):
        tags = ability.get(key, [])
        unknown = set(tags) - ALL_TAGS
        if unknown:
            raise KnowledgeError(f"{source}: ability {ability['name']}.{key} tiene tags desconocidos {sorted(unknown)}")
    available_from = ability.get("available_from", Phase.EARLY_LANE.value)
    if available_from not in VALID_PHASES:
        raise KnowledgeError(f"{source}: available_from inválido '{available_from}' en {ability['name']}")


def _validate_spike(spike: dict, source: str) -> None:
    required = {"phase", "magnitude", "reason"}
    missing = required - spike.keys()
    if missing:
        raise KnowledgeError(f"{source}: spike sin claves {sorted(missing)}: {spike}")
    if spike["phase"] not in VALID_PHASES:
        raise KnowledgeError(f"{source}: spike.phase inválido '{spike['phase']}'")
    if not isinstance(spike["magnitude"], int) or not (AXIS_MIN <= spike["magnitude"] <= AXIS_MAX):
        raise KnowledgeError(f"{source}: spike.magnitude debe ser un entero entre {AXIS_MIN} y {AXIS_MAX}")
