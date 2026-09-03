"""Vocabulario cerrado del dominio.

Todo lo que las reglas pueden consultar vive acá como enum o constante.
Mantener este vocabulario pequeño y explícito es lo que permite que las
reglas generales sean genéricas (operan sobre ejes/tags/kinds) en vez de
mencionar campeones por nombre.
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
    """Patrón de intercambio dominante que busca el campeón."""

    SHORT_TRADE = "short_trade"
    EXTENDED_TRADE = "extended_trade"
    POKE = "poke"
    ALL_IN_ONLY = "all_in_only"


class Tag(str, Enum):
    """Rasgos cualitativos (no graduables) que las reglas consultan."""

    PERCENT_HEALTH_DAMAGE = "percent_health_damage"
    TRUE_DAMAGE_SOURCE = "true_damage_source"
    ARMOR_SHRED = "armor_shred"
    ATTACK_SPEED_SLOW = "attack_speed_slow"
    AUTO_ATTACK_RELIANT = "auto_attack_reliant"
    HARD_CC = "hard_cc"
    GAP_CLOSER = "gap_closer"
    RANGED_POKE = "ranged_poke"
    DASH_DEPENDENT = "dash_dependent"
    STACKING_MECHANIC = "stacking_mechanic"
    HEALING_REDUCTION_VULNERABLE = "healing_reduction_vulnerable"
    IMMOBILE = "immobile"
    EXTENDED_FIGHTER = "extended_fighter"
    SHORT_TRADER = "short_trader"
    MAGIC_DAMAGE_HEAVY = "magic_damage_heavy"
    PHYSICAL_DAMAGE_HEAVY = "physical_damage_heavy"
    SUSTAINED_DPS_RELIANT = "sustained_dps_reliant"


ALL_TAGS: frozenset[str] = frozenset(t.value for t in Tag)


class EffectKind(str, Enum):
    """Naturaleza estructural de un efecto de habilidad.

    Las reglas generales cruzan `EffectKind` + `counters/countered_by`
    (tags), nunca el nombre de la habilidad. El nombre es solo para
    lectura humana en la traza.
    """

    STACKING_DOT = "stacking_dot"
    ISOLATION = "isolation"
    DEFENSIVE_STANCE = "defensive_stance"
    TRUE_DAMAGE_EXECUTE = "true_damage_execute"
    GAP_CLOSER = "gap_closer"
    SHIELD = "shield"
    HARD_CC_APPLICATION = "hard_cc_application"
    WAVECLEAR_TOOL = "waveclear_tool"


class CooldownClass(str, Enum):
    """Clase de cooldown: determina si una habilidad abre una ventana."""

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
