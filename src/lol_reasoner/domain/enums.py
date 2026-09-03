"""Vocabulario cerrado del dominio.

Todo lo que las reglas pueden consultar vive acá como enum o constante.
Disciplina de vocabulario (hito 1.5): un miembro de `EffectType` o
`TacticalUse` solo se agrega cuando al menos una regla lo consume
realmente (verificado por tests/test_vocabulary_alive.py); no se agregan
miembros "por completitud". `Tag` queda deliberadamente vacío en este
hito — ver el comentario al final del archivo con el vocabulario
potencial documentado para campeones futuros.
"""

from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    """Fases de progresión de la partida que la V0 modela.

    FIRST_ITEM es una fase aproximada de progresión de poder, NO asume
    qué objeto compró cada campeón. Cualquier conclusión que dependiera
    de un objeto concreto debe declararse como información faltante.
    """

    EARLY_LANE = "early_lane"
    LEVEL_6 = "level_6"
    FIRST_ITEM = "first_item"
    SIDE_LANE_LATE = "side_lane_late"


ALL_PHASES: tuple[Phase, ...] = (
    Phase.EARLY_LANE,
    Phase.LEVEL_6,
    Phase.FIRST_ITEM,
    Phase.SIDE_LANE_LATE,
)


def phase_index(phase: Phase) -> int:
    return ALL_PHASES.index(phase)


def is_available_in(available_from: Phase, phase: Phase) -> bool:
    """True si algo disponible desde `available_from` ya existe en `phase`."""

    return phase_index(available_from) <= phase_index(phase)


class Axis(str, Enum):
    """Ejes semánticos graduados 0..4 (ninguno/bajo/medio/alto/extremo)."""

    ATTACK_RANGE = "attack_range"
    MOBILITY = "mobility"
    SUSTAIN = "sustain"
    BURST = "burst"
    SUSTAINED_DPS = "sustained_dps"
    CC = "cc"
    DURABILITY = "durability"
    WAVECLEAR = "waveclear"
    EARLY_PRESSURE = "early_pressure"
    SCALING = "scaling"
    ALL_IN = "all_in"
    DISENGAGE = "disengage"
    ABILITY_RELIANCE = "ability_reliance"
    EXECUTION_DEMAND = "execution_demand"


ALL_AXES: tuple[Axis, ...] = tuple(Axis)
AXIS_MIN = 0
AXIS_MAX = 4


class TradePattern(str, Enum):
    """Vocabulario para el resumen descriptivo `Champion.trade_patterns`.

    Puramente informativo para la salida humana: ninguna regla lo lee.
    Las reglas inspeccionan `tactical_uses` de las habilidades concretas
    disponibles en cada fase, no esta etiqueta agregada.
    """

    SHORT_TRADE = "short_trade"
    EXTENDED_TRADE = "extended_trade"
    POKE = "poke"
    ALL_IN_ONLY = "all_in_only"


class DamageType(str, Enum):
    PHYSICAL = "physical"
    MAGIC = "magic"
    TRUE = "true"


class ResourceType(str, Enum):
    """Recurso de lanzamiento del campeón (`Champion.casting_resource`).

    No es la mecánica de escudo/recurso especial de una habilidad puntual
    (eso vive en los `Effect` de esa habilidad, p. ej. `SHIELD_FROM_STORED`
    de Indestructible): esto es el recurso que limita lanzar habilidades
    en general.
    """

    MANA = "mana"
    ENERGY = "energy"
    RESOURCELESS = "resourceless"
    HEALTH_COST = "health_cost"
    SPECIAL_RESOURCE = "special_resource"


class Tag(str, Enum):
    """Propiedades permanentes del campeón, verdaderamente ortogonales a
    axes/effects/tactical_uses/damage_type/casting_resource.

    Deliberadamente vacío en este hito: ni Darius ni Mordekaiser necesitan
    hoy una propiedad que no sea ya expresable por esos otros campos, y
    mantener miembros "por si acaso" es exactamente el vocabulario muerto
    que este refactor corrige. Ver el bloque de vocabulario potencial más
    abajo para lo que se activará cuando un campeón futuro lo necesite.
    """


ALL_TAGS: frozenset[str] = frozenset(t.value for t in Tag)


class EffectType(str, Enum):
    """Qué hace un efecto de habilidad, a nivel estructural.

    Cada miembro tiene al menos una regla que lo consume (ver
    tests/test_vocabulary_alive.py). Un efecto que ninguna regla lee no
    pertenece acá: pertenece a `Ability.doc`.
    """

    DAMAGE = "damage"
    HEAL = "heal"
    SLOW = "slow"
    DISPLACE_ENEMY = "displace_enemy"          # mueve al RIVAL; nunca al que castea
    SELF_DASH = "self_dash"                     # reposicionamiento propio real
    BRIEF_CC = "brief_cc"
    INTERRUPT = "interrupt"
    AUTO_ATTACK_RESET = "auto_attack_reset"
    EMPOWER_NEXT_ATTACK = "empower_next_attack"
    STACK_APPLICATION = "stack_application"
    AMPLIFY_ABILITY = "amplify_ability"          # escala otra habilidad (ver `amplifies_slot`)
    EMPOWER_SELF = "empower_self"
    SHIELD_FROM_STORED = "shield_from_stored"      # escudo construido a partir de un recurso acumulado
    CONVERT_SHIELD_TO_HEAL = "convert_shield_to_heal"
    AURA_DAMAGE = "aura_damage"
    MOVEMENT_SPEED = "movement_speed"
    MAGIC_PENETRATION = "magic_penetration"
    ARMOR_PENETRATION = "armor_penetration"
    STAT_STEAL = "stat_steal"
    ISOLATE_DUEL = "isolate_duel"                    # sin ayuda externa; en esta V0 nunca puntúa por sí solo
    RESTRICT_ARENA = "restrict_arena"
    COOLDOWN_RESET = "cooldown_reset"


class EffectCondition(str, Enum):
    """Bajo qué circunstancia se activa un efecto. Un `Effect` puede tener
    varias simultáneas (`Effect.conditions: frozenset[EffectCondition]`)."""

    ON_HIT = "on_hit"
    ON_OUTER_ZONE = "on_outer_zone"
    ON_INNER_ZONE = "on_inner_zone"
    TARGET_IS_CHAMPION = "target_is_champion"
    ON_ISOLATED_TARGET = "on_isolated_target"
    ON_DELAY = "on_delay"
    ON_REACTIVATION = "on_reactivation"
    ON_TAKEDOWN = "on_takedown"


class TacticalUse(str, Enum):
    """Para qué sirve una habilidad en la práctica (no qué hace mecánicamente:
    eso ya está en `effects`). Cada miembro tiene un consumidor real (ver
    tests/test_vocabulary_alive.py).

    `DISENGAGE` queda deliberadamente fuera: ni Darius ni Mordekaiser
    tienen una herramienta real de desconexión en este hito (Apprehend
    específicamente NO lo es). Se documenta como vocabulario potencial
    más abajo.
    """

    INITIATE = "initiate"
    ANTI_KITE = "anti_kite"
    SETUP_COMBO = "setup_combo"
    POKE = "poke"
    WAVECLEAR = "waveclear"
    SUSTAIN = "sustain"
    TRADE_EXTEND = "trade_extend"
    TRADE_CUT = "trade_cut"


class CooldownClass(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class Polarity(str, Enum):
    PRO = "pro"
    CONTRA = "contra"
    CONDITIONAL = "conditional"


class Factor(str, Enum):
    """Factores de scoring, con pesos centralizados en config/weights.yaml."""

    MECHANICAL_INTERACTION = "mechanical_interaction"
    LANE_PATTERN = "lane_pattern"
    RELIABILITY = "reliability"
    POWER_SPIKES = "power_spikes"
    SCALING_SIDELANE = "scaling_sidelane"
    EXECUTION_DEMAND = "execution_demand"


ALL_FACTORS: tuple[Factor, ...] = tuple(Factor)


class ConfidenceLevel(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"


# ---------------------------------------------------------------------------
# Vocabulario potencial (NO activo en este hito)
# ---------------------------------------------------------------------------
# Documentado por pedido explícito: podar sin descartar. Se activa un
# término de esta lista moviéndolo a un enum de arriba únicamente cuando
# las tres condiciones se cumplan a la vez:
#   1. Un campeón nuevo posee realmente esa propiedad.
#   2. Existe una regla que la consume.
#   3. Existe un test que demuestra el comportamiento.
#
# Candidatos a `Tag` (propiedades permanentes):
#   - percent_health_damage: daño que escala con la vida (máxima o actual)
#     del objetivo en vez de con stats propias.
#   - attack_speed_slow: fuente de reducción de velocidad de ataque como
#     rasgo central del kit (no un slow de movimiento puntual).
#   - dash_dependent: el plan del campeón depende de un dash con cooldown
#     largo, más allá de si ese dash es SELF_DASH ofensivo o defensivo.
#   - ranged_poke: identidad de poke a distancia dominante (a diferencia
#     de un poke ocasional de un kit principalmente de trade extendido,
#     como el Q de Mordekaiser en este hito).
#   - short_trader: identidad de trade corto/hit-and-run como patrón
#     dominante (ninguno de Darius/Mordekaiser lo es).
#
# Candidato a `TacticalUse`:
#   - disengage: una herramienta que de verdad permite desconectar un
#     intercambio (romper línea de visión, ganar distancia neta). Apprehend
#     NO calza: desplaza al rival, no crea espacio para quien la usa.
# ---------------------------------------------------------------------------
