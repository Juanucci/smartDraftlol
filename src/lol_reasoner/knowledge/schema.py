"""Validación de la forma esperada de un YAML de campeón — schema v2.

Deliberadamente manual (sin pydantic ni jsonschema) para mantener la
única dependencia del proyecto en `pyyaml`. Los mensajes de error están
pensados para ser accionables al editar un YAML a mano, y rechazan
explícitamente las claves del schema v1 (hito 1) en vez de ignorarlas
en silencio, para que migrar un YAML viejo falle rápido y señale a
dónde migrar cada campo.
"""

from __future__ import annotations

from lol_reasoner.domain.enums import (
    ALL_AXES,
    ALL_TAGS,
    AXIS_MAX,
    AXIS_MIN,
    CooldownClass,
    DamageType,
    EffectCondition,
    EffectType,
    Phase,
    ResourceType,
    TacticalUse,
    TradePattern,
)

SCHEMA_VERSION = 3

REQUIRED_TOP_LEVEL_KEYS = {
    "schema_version",
    "id",
    "name",
    "archetype",
    "damage_profile",
    "axes",
    "casting_resource",
    "trade_patterns",
    "tags",
    "abilities",
    "stacking_mechanics",
    "spikes",
    "knowledge_version",
}

# Claves del schema v1 (hito 1) que ya no existen. Si aparecen, el error
# apunta explícitamente a dónde migró cada una, en vez de ignorarlas.
LEGACY_TOP_LEVEL_KEYS = {
    "trade_pattern": "trade_patterns (ahora un conjunto; además, la fuente de verdad para las reglas son los `tactical_uses` de cada habilidad, no este resumen)",
    "strengths": "eliminado: debe surgir de la traza, no declararse a mano",
    "vulnerabilities": "eliminado: debe surgir de la traza, no declararse a mano",
}
LEGACY_ABILITY_KEYS = {
    "kind": "effects (una lista; una habilidad puede tener varios efectos)",
    "counters": "eliminado: las reglas cruzan `effects` estructuralmente, no listas de tags-contra-tags",
    "countered_by": "eliminado: idem `counters`",
    "note": "doc",
}

REQUIRED_AXIS_NAMES = {a.value for a in ALL_AXES}
REQUIRED_SLOTS = {"P", "Q", "W", "E", "R"}
VALID_PHASES = {p.value for p in Phase}
VALID_EFFECT_TYPES = {k.value for k in EffectType}
VALID_EFFECT_CONDITIONS = {c.value for c in EffectCondition}
VALID_DAMAGE_TYPES = {d.value for d in DamageType}
VALID_COOLDOWN_CLASSES = {c.value for c in CooldownClass}
VALID_TRADE_PATTERNS = {t.value for t in TradePattern}
VALID_TACTICAL_USES = {t.value for t in TacticalUse}
VALID_RESOURCE_TYPES = {r.value for r in ResourceType}
VALID_STACK_APPLICATION_SOURCES = {"basic_attack", "Q", "W", "E", "R"}
# Dirección de un DISPLACE_ENEMY (ver domain/champion.py: Effect.displacement_vector).
VALID_DISPLACEMENT_VECTORS = {"toward_self", "away"}
# Alcance de un efecto de empoderamiento (ver domain/champion.py: Effect.scope).
VALID_EFFECT_SCOPES = {"offensive_profile"}


class KnowledgeError(ValueError):
    """Error de validación de un archivo de la base de conocimiento."""


def validate_champion_dict(data: dict, *, source: str) -> None:
    legacy_hit = LEGACY_TOP_LEVEL_KEYS.keys() & data.keys()
    if legacy_hit:
        detail = "; ".join(f"'{k}' -> {LEGACY_TOP_LEVEL_KEYS[k]}" for k in sorted(legacy_hit))
        raise KnowledgeError(f"{source}: claves del schema v1 ya no soportadas: {detail}")

    if data.get("schema_version") != SCHEMA_VERSION:
        raise KnowledgeError(f"{source}: schema_version debe ser {SCHEMA_VERSION}, encontrado {data.get('schema_version')!r}")

    missing = REQUIRED_TOP_LEVEL_KEYS - data.keys()
    if missing:
        raise KnowledgeError(f"{source}: faltan claves obligatorias: {sorted(missing)}")

    _validate_damage_profile(data["damage_profile"], source)
    _validate_axes(data["axes"], source)

    if data["casting_resource"] not in VALID_RESOURCE_TYPES:
        raise KnowledgeError(f"{source}: casting_resource inválido '{data['casting_resource']}'")

    unknown_patterns = set(data["trade_patterns"]) - VALID_TRADE_PATTERNS
    if unknown_patterns:
        raise KnowledgeError(f"{source}: trade_patterns desconocidos {sorted(unknown_patterns)}")

    unknown_tags = set(data["tags"]) - ALL_TAGS
    if unknown_tags:
        raise KnowledgeError(
            f"{source}: tags desconocidos {sorted(unknown_tags)}. Tag está vacío en este hito "
            "(ver domain/enums.py); si es un concepto genuinamente nuevo, primero agregalo al "
            "enum con una regla que lo consuma y un test."
        )

    if not isinstance(data["abilities"], list):
        raise KnowledgeError(f"{source}: 'abilities' debe ser una lista")
    slots_seen = {a.get("slot") for a in data["abilities"]}
    if slots_seen != REQUIRED_SLOTS:
        raise KnowledgeError(f"{source}: abilities debe cubrir exactamente los slots {sorted(REQUIRED_SLOTS)}, encontrado {sorted(slots_seen)}")
    stack_ids = {m["id"] for m in data["stacking_mechanics"] if isinstance(m, dict) and "id" in m}
    for ability in data["abilities"]:
        _validate_ability(ability, source, stack_ids)

    if not isinstance(data["stacking_mechanics"], list):
        raise KnowledgeError(f"{source}: 'stacking_mechanics' debe ser una lista")
    for mechanic in data["stacking_mechanics"]:
        _validate_stacking_mechanic(mechanic, source)
    _validate_stack_consistency(data, source)

    if not isinstance(data["spikes"], list):
        raise KnowledgeError(f"{source}: 'spikes' debe ser una lista")
    for spike in data["spikes"]:
        _validate_spike(spike, source)

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


def _validate_ability(ability: dict, source: str, stack_ids: set[str]) -> None:
    legacy_hit = LEGACY_ABILITY_KEYS.keys() & ability.keys()
    if legacy_hit:
        name = ability.get("name", "?")
        detail = "; ".join(f"'{k}' -> {LEGACY_ABILITY_KEYS[k]}" for k in sorted(legacy_hit))
        raise KnowledgeError(f"{source}: ability {name} usa claves del schema v1: {detail}")

    required = {"slot", "name", "cooldown_class", "effects"}
    missing = required - ability.keys()
    if missing:
        raise KnowledgeError(f"{source}: ability {ability.get('name', '?')} sin claves {sorted(missing)}")
    if ability["slot"] not in REQUIRED_SLOTS:
        raise KnowledgeError(f"{source}: slot inválido '{ability['slot']}'")
    if ability["cooldown_class"] not in VALID_COOLDOWN_CLASSES:
        raise KnowledgeError(f"{source}: cooldown_class inválido '{ability['cooldown_class']}' en {ability['name']}")

    unknown_uses = set(ability.get("tactical_uses", [])) - VALID_TACTICAL_USES
    if unknown_uses:
        raise KnowledgeError(f"{source}: tactical_uses desconocidos {sorted(unknown_uses)} en {ability['name']}")

    available_from = ability.get("available_from", Phase.EARLY_LANE.value)
    if available_from not in VALID_PHASES:
        raise KnowledgeError(f"{source}: available_from inválido '{available_from}' en {ability['name']}")

    if not isinstance(ability["effects"], list) or not ability["effects"]:
        raise KnowledgeError(f"{source}: {ability['name']}.effects debe ser una lista no vacía")
    for effect in ability["effects"]:
        _validate_effect(effect, source, ability["name"], stack_ids)


def _validate_effect(effect: dict, source: str, ability_name: str, stack_ids: set[str]) -> None:
    required = {"type", "magnitude"}
    missing = required - effect.keys()
    if missing:
        raise KnowledgeError(f"{source}: efecto de {ability_name} sin claves {sorted(missing)}: {effect}")
    if effect["type"] not in VALID_EFFECT_TYPES:
        raise KnowledgeError(f"{source}: effect.type inválido '{effect['type']}' en {ability_name}, ver EffectType")
    magnitude = effect["magnitude"]
    if not isinstance(magnitude, int) or not (AXIS_MIN <= magnitude <= AXIS_MAX):
        raise KnowledgeError(f"{source}: effect.magnitude={magnitude!r} inválido en {ability_name} (0..4)")

    conditions = effect.get("conditions", [])
    unknown_conditions = set(conditions) - VALID_EFFECT_CONDITIONS
    if unknown_conditions:
        raise KnowledgeError(f"{source}: conditions desconocidas {sorted(unknown_conditions)} en {ability_name}")

    damage_type = effect.get("damage_type")
    if damage_type is not None and damage_type not in VALID_DAMAGE_TYPES:
        raise KnowledgeError(f"{source}: damage_type inválido '{damage_type}' en {ability_name}")

    feeds_stack = effect.get("feeds_stack")
    if feeds_stack is not None and feeds_stack not in stack_ids:
        raise KnowledgeError(f"{source}: feeds_stack '{feeds_stack}' en {ability_name} no referencia ninguna stacking_mechanic declarada")
    if feeds_stack is not None and effect["type"] != EffectType.STACK_APPLICATION.value:
        raise KnowledgeError(f"{source}: feeds_stack solo tiene sentido en un efecto STACK_APPLICATION ({ability_name})")

    stack_scaling = effect.get("stack_scaling")
    if stack_scaling is not None and stack_scaling not in stack_ids:
        raise KnowledgeError(f"{source}: stack_scaling '{stack_scaling}' en {ability_name} no referencia ninguna stacking_mechanic declarada")

    scope = effect.get("scope")
    if scope is not None and scope not in VALID_EFFECT_SCOPES:
        raise KnowledgeError(
            f"{source}: scope inválido '{scope}' en {ability_name}, debe ser uno de {sorted(VALID_EFFECT_SCOPES)}"
        )

    displacement_vector = effect.get("displacement_vector")
    if displacement_vector is not None:
        if displacement_vector not in VALID_DISPLACEMENT_VECTORS:
            raise KnowledgeError(
                f"{source}: displacement_vector inválido '{displacement_vector}' en {ability_name}, "
                f"debe ser uno de {sorted(VALID_DISPLACEMENT_VECTORS)}"
            )
        if effect["type"] != EffectType.DISPLACE_ENEMY.value:
            raise KnowledgeError(
                f"{source}: displacement_vector solo tiene sentido en un efecto DISPLACE_ENEMY ({ability_name})"
            )

    amplifies_slot = effect.get("amplifies_slot")
    if amplifies_slot is not None and amplifies_slot not in REQUIRED_SLOTS:
        raise KnowledgeError(f"{source}: amplifies_slot inválido '{amplifies_slot}' en {ability_name}")


def _validate_stacking_mechanic(mechanic: dict, source: str) -> None:
    required = {"id", "name", "threshold", "stacks_per_application", "applied_by", "reward_name"}
    missing = required - mechanic.keys()
    if missing:
        raise KnowledgeError(f"{source}: stacking_mechanic sin claves {sorted(missing)}: {mechanic}")
    if not isinstance(mechanic["threshold"], int) or mechanic["threshold"] <= 0:
        raise KnowledgeError(f"{source}: threshold inválido en {mechanic['id']}")
    if not isinstance(mechanic["stacks_per_application"], int) or mechanic["stacks_per_application"] <= 0:
        raise KnowledgeError(f"{source}: stacks_per_application inválido en {mechanic['id']}")
    applied_by = mechanic["applied_by"]
    if not applied_by or set(applied_by) - VALID_STACK_APPLICATION_SOURCES:
        raise KnowledgeError(f"{source}: applied_by inválido en {mechanic['id']}, debe ser un subconjunto no vacío de {sorted(VALID_STACK_APPLICATION_SOURCES)}")
    for effect in mechanic.get("reward_effects", []):
        _validate_effect(effect, source, f"{mechanic['id']}.reward", {mechanic["id"]})


def _validate_stack_consistency(data: dict, source: str) -> None:
    """Cruza `stacking_mechanic.applied_by` contra los efectos reales de
    las habilidades: si una mecánica declara que el slot Q la alimenta,
    la habilidad Q debe tener de verdad un efecto STACK_APPLICATION que
    la referencie por `feeds_stack`. Evita que ambas declaraciones se
    desincronicen (p. ej. que se borre el efecto de una habilidad pero
    quede su slot colgando en `applied_by`)."""

    abilities_by_slot = {a["slot"]: a for a in data["abilities"]}
    for mechanic in data["stacking_mechanics"]:
        for slot in mechanic["applied_by"]:
            if slot == "basic_attack":
                continue  # no hay un objeto Ability para el auto-ataque en este modelo
            ability = abilities_by_slot.get(slot)
            if ability is None:
                raise KnowledgeError(f"{source}: {mechanic['id']}.applied_by referencia el slot '{slot}', que no existe")
            feeds = [
                e for e in ability["effects"]
                if e["type"] == EffectType.STACK_APPLICATION.value and e.get("feeds_stack") == mechanic["id"]
            ]
            if not feeds:
                raise KnowledgeError(
                    f"{source}: {mechanic['id']}.applied_by incluye '{slot}', pero {ability['name']} no tiene "
                    f"ningún efecto STACK_APPLICATION con feeds_stack='{mechanic['id']}'"
                )


def _validate_spike(spike: dict, source: str) -> None:
    required = {"phase", "magnitude", "reason"}
    missing = required - spike.keys()
    if missing:
        raise KnowledgeError(f"{source}: spike sin claves {sorted(missing)}: {spike}")
    if spike["phase"] not in VALID_PHASES:
        raise KnowledgeError(f"{source}: spike.phase inválido '{spike['phase']}'")
    if not isinstance(spike["magnitude"], int) or not (AXIS_MIN <= spike["magnitude"] <= AXIS_MAX):
        raise KnowledgeError(f"{source}: spike.magnitude debe ser un entero entre {AXIS_MIN} y {AXIS_MAX}")
