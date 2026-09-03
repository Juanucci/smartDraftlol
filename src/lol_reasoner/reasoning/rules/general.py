"""Reglas generales de interacción mecánica.

RESTRICCIÓN DURA (verificada por tests/test_no_hardcoded_pairs.py):
ninguna regla de este archivo puede contener un literal con el `id` o
`name` de un campeón. Solo pueden leer `axes`, `tags`, `trade_pattern`,
`damage_profile` y `abilities[].kind/counters/countered_by/cooldown_class`.
Cualquier interacción que de verdad solo tenga sentido entre dos kits
puntuales va en `specific.py`, con justificación explícita.

Cada regla documenta, en su docstring, qué principio general del
diseño representa (los que pediste en el brief).
"""

from __future__ import annotations

from lol_reasoner.domain.enums import ALL_PHASES, Axis, CooldownClass, EffectKind, Factor, Phase, Polarity, TradePattern
from lol_reasoner.reasoning.context import ReasoningContext
from lol_reasoner.reasoning.rules.base import Rule, RuleEffect
from lol_reasoner.reasoning.trace import FactRef

_LANE_PHASES = frozenset({Phase.EARLY_LANE, Phase.SIDE_LANE_LATE})
_SIDE_ONLY = frozenset({Phase.SIDE_LANE_LATE})
_FROM_6 = frozenset({Phase.LEVEL_6, Phase.FIRST_ITEM, Phase.SIDE_LANE_LATE})


def _phase_index(phase: Phase) -> int:
    return ALL_PHASES.index(phase)


class RangeAccessRule(Rule):
    """El rango y el kite castigan a campeones con poco acceso al objetivo."""

    id = "G01"
    summary = "Una ventaja de rango de ataque, si el rival no puede cerrarla, castiga su acceso al objetivo."
    category = "range_access"
    phases = _LANE_PHASES

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        range_diff = ctx.candidate.axis(Axis.ATTACK_RANGE) - ctx.enemy.axis(Axis.ATTACK_RANGE)
        enemy_mobility = ctx.enemy.axis(Axis.MOBILITY)
        enemy_has_gap_closer = any(a.kind == EffectKind.GAP_CLOSER for a in ctx.enemy.abilities)
        if range_diff >= 2 and enemy_mobility <= 1 and not enemy_has_gap_closer:
            delta = min(0.6, 0.2 * range_diff)
            return [
                RuleEffect(
                    factor=Factor.LANE_PATTERN,
                    polarity=Polarity.PRO,
                    delta=delta,
                    text=(
                        f"{ctx.candidate.name} tiene más rango de ataque que {ctx.enemy.name} "
                        f"({ctx.candidate.axis(Axis.ATTACK_RANGE)} vs {ctx.enemy.axis(Axis.ATTACK_RANGE)}) "
                        f"y {ctx.enemy.name} no dispone de una herramienta fiable para cerrar esa distancia, "
                        "lo que castiga su acceso al objetivo."
                    ),
                    premises=(
                        FactRef(f"{ctx.candidate.id}.axes.attack_range", ctx.candidate.axis(Axis.ATTACK_RANGE)),
                        FactRef(f"{ctx.enemy.id}.axes.attack_range", ctx.enemy.axis(Axis.ATTACK_RANGE)),
                        FactRef(f"{ctx.enemy.id}.axes.mobility", enemy_mobility),
                        FactRef(f"{ctx.enemy.id}.abilities.gap_closer", False),
                    ),
                    condition="mientras se conserve el espacio y no se reciba control duro de cierre de distancia",
                )
            ]
        return []


class PokeVsSustainRule(Rule):
    """El sustain reduce el valor del poke si el rival no puede concretar un all-in."""

    id = "G02"
    summary = "El poke pierde valor de conversión cuando el rival tiene sustain alto."
    category = "poke_vs_sustain"
    phases = frozenset({Phase.EARLY_LANE, Phase.FIRST_ITEM})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        if ctx.candidate.trade_pattern != TradePattern.POKE:
            return []
        effects = [
            RuleEffect(
                factor=Factor.LANE_PATTERN,
                polarity=Polarity.PRO,
                delta=0.25,
                text=f"{ctx.candidate.name} impone un patrón de poke que erosiona vida sin exponerse en trades cortos.",
                premises=(FactRef(f"{ctx.candidate.id}.trade_pattern", ctx.candidate.trade_pattern.value),),
            )
        ]
        enemy_sustain = ctx.enemy.axis(Axis.SUSTAIN)
        if enemy_sustain >= 3:
            effects.append(
                RuleEffect(
                    factor=Factor.LANE_PATTERN,
                    polarity=Polarity.CONTRA,
                    delta=0.2 * enemy_sustain / 4,
                    text=(
                        f"El sustain alto de {ctx.enemy.name} licua buena parte del poke de {ctx.candidate.name} "
                        "si no viene acompañado de una amenaza real de all-in."
                    ),
                    premises=(FactRef(f"{ctx.enemy.id}.axes.sustain", enemy_sustain),),
                    condition="se sostiene solo si el poke no puede convertirse en un all-in cuando el rival gasta sustain",
                )
            )
        return effects


class DamageTypeRetainsValueRule(Rule):
    """El daño mágico/verdadero conserva valor frente a resistencias acumuladas."""

    id = "G03"
    summary = "El componente de daño verdadero o mágico de un kit no se diluye ante durabilidad física acumulada."
    category = "damage_type_vs_durability"
    phases = _FROM_6

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        true_frac = ctx.candidate.damage_profile.true
        if true_frac >= 0.15 and ctx.enemy.axis(Axis.DURABILITY) >= 3:
            return [
                RuleEffect(
                    factor=Factor.MECHANICAL_INTERACTION,
                    polarity=Polarity.PRO,
                    delta=0.3 * true_frac / 0.2,
                    text=(
                        f"Una porción relevante del daño de {ctx.candidate.name} es daño verdadero, "
                        f"que conserva su valor completo sin importar cuánta durabilidad acumule {ctx.enemy.name}."
                    ),
                    premises=(
                        FactRef(f"{ctx.candidate.id}.damage_profile.true", true_frac),
                        FactRef(f"{ctx.enemy.id}.axes.durability", ctx.enemy.axis(Axis.DURABILITY)),
                    ),
                )
            ]
        return []


class AbilityCounterRule(Rule):
    """Cruce genérico kit-vs-kit: habilidades que anulan (o son anuladas por) tags rivales.

    Implementa a la vez:
      - "una habilidad defensiva puede negar un patrón rival"
      - "...pero su cooldown crea una ventana castigable"
    sin nombrar ninguna habilidad ni campeón puntual: solo cruza
    `AbilityEffect.counters`/`countered_by` (tags) contra los tags del
    rival.
    """

    id = "G04"
    summary = "Una habilidad cuyo `counters` incluye un tag del rival niega ese patrón; su cooldown abre una ventana."
    category = "ability_interaction"

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []

        for ability in ctx.candidate.abilities:
            hit = ability.counters & ctx.enemy.tags
            if hit:
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.PRO,
                        delta=0.15 * len(hit),
                        text=(
                            f"{ctx.candidate.name} tiene en {ability.name} ({ability.slot}) una herramienta que "
                            f"niega el patrón de {ctx.enemy.name} asociado a: {', '.join(sorted(hit))}."
                        ),
                        premises=(
                            FactRef(f"{ctx.candidate.id}.abilities.{ability.slot}.counters", sorted(hit)),
                            FactRef(f"{ctx.enemy.id}.tags", sorted(hit)),
                        ),
                    )
                )
            broken = ctx.enemy.tags & ability.countered_by
            if broken:
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.CONTRA,
                        delta=0.1 * len(broken),
                        text=(
                            f"{ability.name} ({ability.slot}) de {ctx.candidate.name} es específicamente "
                            f"vulnerable al patrón de {ctx.enemy.name} asociado a: {', '.join(sorted(broken))}."
                        ),
                        premises=(
                            FactRef(f"{ctx.candidate.id}.abilities.{ability.slot}.countered_by", sorted(broken)),
                            FactRef(f"{ctx.enemy.id}.tags", sorted(broken)),
                        ),
                    )
                )

        for ability in ctx.enemy.abilities:
            broken = ctx.candidate.tags & ability.countered_by
            if broken:
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.PRO,
                        delta=0.1 * len(broken),
                        text=(
                            f"El patrón de {ctx.candidate.name} asociado a {', '.join(sorted(broken))} atraviesa "
                            f"específicamente {ability.name} ({ability.slot}) de {ctx.enemy.name}."
                        ),
                        premises=(
                            FactRef(f"{ctx.enemy.id}.abilities.{ability.slot}.countered_by", sorted(broken)),
                            FactRef(f"{ctx.candidate.id}.tags", sorted(broken)),
                        ),
                    )
                )
            hit = ability.counters & ctx.candidate.tags
            if not hit:
                continue
            effects.append(
                RuleEffect(
                    factor=Factor.MECHANICAL_INTERACTION,
                    polarity=Polarity.CONTRA,
                    delta=0.15 * len(hit),
                    text=(
                        f"{ctx.enemy.name} tiene en {ability.name} ({ability.slot}) una herramienta que niega el "
                        f"patrón de {ctx.candidate.name} asociado a: {', '.join(sorted(hit))}."
                    ),
                    premises=(
                        FactRef(f"{ctx.enemy.id}.abilities.{ability.slot}.counters", sorted(hit)),
                        FactRef(f"{ctx.candidate.id}.tags", sorted(hit)),
                    ),
                )
            )
            # El "aviso de ventana de cooldown" es un hecho estructural del kit,
            # no algo que cambie fase a fase: se reporta una sola vez (en
            # EARLY_LANE si esa fase está en la consulta) para no inflar
            # `conditional_count` con la misma observación repetida por fase.
            if ability.cooldown_class != CooldownClass.SHORT and ctx.phase == Phase.EARLY_LANE:
                effects.append(
                    RuleEffect(
                        factor=Factor.POWER_SPIKES,
                        polarity=Polarity.CONDITIONAL,
                        delta=0.1 * len(hit),
                        text=(
                            f"Mientras {ability.name} de {ctx.enemy.name} esté en cooldown "
                            f"({ability.cooldown_class.value}), {ctx.candidate.name} recupera el valor del "
                            f"patrón que esa habilidad normalmente niega."
                        ),
                        premises=(FactRef(f"{ctx.enemy.id}.abilities.{ability.slot}.cooldown_class", ability.cooldown_class.value),),
                        condition=f"solo aplica en la ventana en que {ability.name} está en cooldown",
                        invalidated_if=f"no se modela el timing exacto de cooldown de {ability.name} en esta V0",
                        category="cooldown_window",
                    )
                )
        return effects


class IsolationUltimateRule(Rule):
    """Un ultimate que aísla al rival reduce el valor de intervenciones externas."""

    id = "G05"
    summary = "Una habilidad de tipo aislamiento reduce, mientras dura, el valor de ayuda externa al rival."
    category = "ultimate_impact"
    phases = _FROM_6

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        isolations = [a for a in ctx.enemy.abilities if a.kind == EffectKind.ISOLATION]
        if not isolations:
            return []
        ability = isolations[0]
        return [
            RuleEffect(
                factor=Factor.MECHANICAL_INTERACTION,
                polarity=Polarity.CONTRA,
                delta=0.15,
                text=(
                    f"{ability.name} de {ctx.enemy.name} aísla el 1v1 y reduce el valor de cualquier intervención "
                    f"externa a favor de {ctx.candidate.name}."
                ),
                premises=(FactRef(f"{ctx.enemy.id}.abilities.{ability.slot}.kind", ability.kind.value),),
                condition="el efecto es mayor cuanto más dependa el candidato de ayuda de aliados o jungla",
                invalidated_if="esta V0 no modela presencia de jungla ni de aliados fuera del 1v1 de lane",
            )
        ]


class TrueDamageExecuteThreatRule(Rule):
    """Una ejecución de daño verdadero es una amenaza condicionada al HP restante."""

    id = "G06"
    summary = "Una habilidad de ejecución por daño verdadero amenaza más cuanto más baja esté la vida del rival."
    category = "execute_threat"
    phases = _FROM_6

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        executes = [a for a in ctx.enemy.abilities if a.kind == EffectKind.TRUE_DAMAGE_EXECUTE]
        if not executes:
            return []
        ability = executes[0]
        return [
            RuleEffect(
                factor=Factor.POWER_SPIKES,
                polarity=Polarity.CONDITIONAL,
                delta=0.15,
                text=(
                    f"{ctx.candidate.name} queda expuesto a {ability.name} de {ctx.enemy.name}, una ejecución de "
                    "daño verdadero cuyo umbral de activación depende del HP restante."
                ),
                premises=(FactRef(f"{ctx.enemy.id}.abilities.{ability.slot}.kind", ability.kind.value),),
                condition="solo es determinante si el HP de la víctima cae bajo el umbral de la ejecución",
                invalidated_if="el HP real durante la partida no se modela en esta V0",
            )
        ]


class EarlyPressureVsScalingRule(Rule):
    """Un campeón fuerte en early puede ser mejor en lane y peor en side lane tardía."""

    id = "G07"
    summary = "La presión temprana y el escalado tardío pueden favorecer a lados opuestos de la lane."
    category = "phase_transition"
    phases = frozenset({Phase.EARLY_LANE, Phase.SIDE_LANE_LATE})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        if ctx.phase == Phase.EARLY_LANE:
            diff = ctx.candidate.axis(Axis.EARLY_PRESSURE) - ctx.enemy.axis(Axis.EARLY_PRESSURE)
            if diff >= 1:
                return [
                    RuleEffect(
                        factor=Factor.LANE_PATTERN,
                        polarity=Polarity.PRO,
                        delta=0.15 * diff,
                        text=(
                            f"{ctx.candidate.name} tiene más presión temprana que {ctx.enemy.name} "
                            f"({ctx.candidate.axis(Axis.EARLY_PRESSURE)} vs {ctx.enemy.axis(Axis.EARLY_PRESSURE)})."
                        ),
                        premises=(
                            FactRef(f"{ctx.candidate.id}.axes.early_pressure", ctx.candidate.axis(Axis.EARLY_PRESSURE)),
                            FactRef(f"{ctx.enemy.id}.axes.early_pressure", ctx.enemy.axis(Axis.EARLY_PRESSURE)),
                        ),
                    )
                ]
        elif ctx.phase == Phase.SIDE_LANE_LATE:
            diff = ctx.enemy.axis(Axis.SCALING) - ctx.candidate.axis(Axis.SCALING)
            if diff >= 1:
                return [
                    RuleEffect(
                        factor=Factor.SCALING_SIDELANE,
                        polarity=Polarity.CONTRA,
                        delta=0.15 * diff,
                        text=(
                            f"{ctx.enemy.name} escala mejor que {ctx.candidate.name} hacia el side lane tardío "
                            f"({ctx.enemy.axis(Axis.SCALING)} vs {ctx.candidate.axis(Axis.SCALING)}), incluso si "
                            "la lane temprana fue favorable."
                        ),
                        premises=(
                            FactRef(f"{ctx.enemy.id}.axes.scaling", ctx.enemy.axis(Axis.SCALING)),
                            FactRef(f"{ctx.candidate.id}.axes.scaling", ctx.candidate.axis(Axis.SCALING)),
                        ),
                        condition="depende de que la partida se extienda y de la ventaja de objetos acumulada",
                    )
                ]
        return []


class WaveclearGatingRule(Rule):
    """Menor waveclear relega a defender la wave mientras el rival gana prioridad de rotación."""

    id = "G08"
    summary = "Una brecha de waveclear relevante cede prioridad de mapa en el side lane tardío."
    category = "waveclear"
    phases = _SIDE_ONLY

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        diff = ctx.enemy.axis(Axis.WAVECLEAR) - ctx.candidate.axis(Axis.WAVECLEAR)
        if diff >= 2:
            return [
                RuleEffect(
                    factor=Factor.SCALING_SIDELANE,
                    polarity=Polarity.CONTRA,
                    delta=0.1 * diff,
                    text=(
                        f"{ctx.candidate.name} tiene menos waveclear que {ctx.enemy.name}, lo que lo relega a "
                        "defender la wave mientras el rival gana prioridad para rotar o presionar otra línea."
                    ),
                    premises=(
                        FactRef(f"{ctx.candidate.id}.axes.waveclear", ctx.candidate.axis(Axis.WAVECLEAR)),
                        FactRef(f"{ctx.enemy.id}.axes.waveclear", ctx.enemy.axis(Axis.WAVECLEAR)),
                    ),
                )
            ]
        return []


class AbilityRelianceReliabilityRule(Rule):
    """Un matchup favorable puede seguir siendo poco confiable si exige ejecución precisa."""

    id = "G09"
    summary = "Alta dependencia de una habilidad clave hace que la ventaja sea condicional a acertarla."
    category = "ability_reliance"
    phases = frozenset({Phase.EARLY_LANE})  # hecho estructural del kit, se reporta una sola vez

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        reliance = ctx.candidate.axis(Axis.ABILITY_RELIANCE)
        if reliance >= 3:
            return [
                RuleEffect(
                    factor=Factor.RELIABILITY,
                    polarity=Polarity.CONDITIONAL,
                    delta=0.1 * (reliance - 2),
                    text=(
                        f"El plan de {ctx.candidate.name} depende en buena medida de acertar/usar bien una "
                        "habilidad clave, no solo de estadísticas base."
                    ),
                    premises=(FactRef(f"{ctx.candidate.id}.axes.ability_reliance", reliance),),
                    condition="si el rival puede esquivar, bloquear o forzar el uso en vacío de esa habilidad, la ventaja cae",
                    invalidated_if="no se modela la habilidad individual del jugador para ejecutar el combo",
                )
            ]
        return []


class ExecutionDemandBaselineRule(Rule):
    """El valor de una interacción depende también de cuánto exige ejecutar el plan."""

    id = "G10"
    summary = "Una exigencia de ejecución por encima (o debajo) del promedio ajusta la confiabilidad práctica del pick."
    category = "execution_demand"
    phases = frozenset({Phase.EARLY_LANE})  # se computa una sola vez, no una vez por fase

    _BASELINE = 2

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        demand = ctx.candidate.axis(Axis.EXECUTION_DEMAND)
        if demand == self._BASELINE:
            return []
        diff = demand - self._BASELINE
        polarity = Polarity.CONTRA if diff > 0 else Polarity.PRO
        return [
            RuleEffect(
                factor=Factor.EXECUTION_DEMAND,
                polarity=polarity,
                delta=abs(diff) * 0.2,
                text=(
                    f"{ctx.candidate.name} exige "
                    + ("más" if diff > 0 else "menos")
                    + " ejecución que el promedio para concretar su plan de lane."
                ),
                premises=(FactRef(f"{ctx.candidate.id}.axes.execution_demand", demand),),
            )
        ]


class AllInFragilityRule(Rule):
    """Un all-in fuerte pero con poca durabilidad sigue siendo una apuesta riesgosa."""

    id = "G11"
    summary = "Alta capacidad de all-in combinada con baja durabilidad mantiene la apuesta como riesgosa."
    category = "all_in_readiness"
    phases = frozenset({Phase.EARLY_LANE})  # hecho estructural del kit, se reporta una sola vez

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        if ctx.candidate.axis(Axis.ALL_IN) >= 3 and ctx.candidate.axis(Axis.DURABILITY) <= 2:
            return [
                RuleEffect(
                    factor=Factor.RELIABILITY,
                    polarity=Polarity.CONDITIONAL,
                    delta=0.15,
                    text=f"{ctx.candidate.name} tiene un all-in fuerte pero poca durabilidad para sostenerlo si falla.",
                    premises=(
                        FactRef(f"{ctx.candidate.id}.axes.all_in", ctx.candidate.axis(Axis.ALL_IN)),
                        FactRef(f"{ctx.candidate.id}.axes.durability", ctx.candidate.axis(Axis.DURABILITY)),
                    ),
                    condition="el riesgo baja si el all-in llega con ventaja previa de vida o de objetos",
                )
            ]
        return []


GENERAL_RULES: tuple[Rule, ...] = (
    RangeAccessRule(),
    PokeVsSustainRule(),
    DamageTypeRetainsValueRule(),
    AbilityCounterRule(),
    IsolationUltimateRule(),
    TrueDamageExecuteThreatRule(),
    EarlyPressureVsScalingRule(),
    WaveclearGatingRule(),
    AbilityRelianceReliabilityRule(),
    ExecutionDemandBaselineRule(),
    AllInFragilityRule(),
)

GENERAL_CATEGORIES: frozenset[str] = frozenset(r.category for r in GENERAL_RULES) | {"cooldown_window"}
