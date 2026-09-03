"""Reglas generales de interacción mecánica — hito 1.5.

RESTRICCIÓN DURA (verificada por tests/test_no_hardcoded_pairs.py):
ninguna regla de este archivo puede comparar el `.id` de un campeón
contra un literal. Leer `.name` para armar texto legible sí está
permitido. Las reglas operan sobre `axes`, `tags`, `casting_resource` y,
sobre todo, sobre `effects`/`tactical_uses` de las habilidades
disponibles en la fase actual (vía `ctx.candidate_abilities()` /
`ctx.enemy_abilities()` — nunca `champion.abilities` directo).

Disciplina anti-doble-conteo: cuando varios `Effect` de una misma
habilidad describen el mismo "momento" causal (p. ej. un desplazamiento
que también trae un control breve y una interrupción), una regla debe
agregarlos en UNA sola `RuleEffect` (usando el máximo, no la suma, de
sus magnitudes) en vez de sumar una ventaja independiente por cada tipo
de efecto. Ver `DisplacementVsMobilityRule` y `MitigationAndDisruptionRule`.

Guardrail temporal de esta V0 (documentado, revisable al incorporar los
otros ocho campeones): máximo 15 clases de regla general. Este archivo
más `stacking.py` suman 14.
"""

from __future__ import annotations

from lol_reasoner.domain.enums import (
    ALL_PHASES,
    Axis,
    DamageType,
    EffectType,
    Factor,
    Phase,
    Polarity,
    TacticalUse,
)
from lol_reasoner.reasoning.context import ReasoningContext
from lol_reasoner.reasoning.rules.base import Rule, RuleEffect
from lol_reasoner.reasoning.trace import FactRef

_LANE_PHASES = frozenset({Phase.EARLY_LANE, Phase.SIDE_LANE_LATE})
_SIDE_ONLY = frozenset({Phase.SIDE_LANE_LATE})

# Efectos que describen el mismo "momento" de control de un desplazamiento:
# se agrupan en una única RuleEffect (ver DisplacementVsMobilityRule).
_CONTROL_MOMENT_TYPES = frozenset({EffectType.DISPLACE_ENEMY, EffectType.BRIEF_CC, EffectType.INTERRUPT})
_DISPLACEMENT_QUALIFYING_USES = frozenset({TacticalUse.INITIATE, TacticalUse.ANTI_KITE, TacticalUse.SETUP_COMBO})
_SUSTAINED_QUALIFYING_USES = frozenset({TacticalUse.TRADE_EXTEND, TacticalUse.SUSTAIN})


def _fact(champion_id: str, ability_slot: str, effect_type: EffectType, value: object) -> FactRef:
    """FactRef con convención uniforme: cita habilidad + tipo de efecto,
    lo que permite verificar comportamiento (tests/test_vocabulary_alive.py)
    sin depender de que el texto humano nombre el EffectType."""

    return FactRef(f"{champion_id}.abilities.{ability_slot}.effects.{effect_type.value}", value)


class RangeAccessRule(Rule):
    """El rango y el kite castigan a campeones con poco acceso al objetivo.

    Requiere que el rival tenga un reposicionamiento PROPIO real
    (`SELF_DASH`): un efecto que desplaza al ENEMIGO (`DISPLACE_ENEMY`,
    como Apprehend) no cuenta como acceso al objetivo para quien lo usa.
    """

    id = "G01"
    summary = "Una ventaja de rango, si el rival no puede cerrarla con un desplazamiento propio, castiga su acceso al objetivo."
    category = "range_access"
    categories = frozenset({"range_access"})
    phases = _LANE_PHASES

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        range_diff = ctx.candidate.axis(Axis.ATTACK_RANGE) - ctx.enemy.axis(Axis.ATTACK_RANGE)
        if range_diff < 2:
            return []
        enemy_has_self_dash = any(
            EffectType.SELF_DASH in a.effect_types() for a in ctx.enemy_abilities()
        )
        if enemy_has_self_dash:
            return []
        delta = min(0.6, 0.2 * range_diff)
        return [
            RuleEffect(
                factor=Factor.LANE_PATTERN,
                polarity=Polarity.PRO,
                delta=delta,
                text=(
                    f"{ctx.candidate.name} tiene más rango de ataque que {ctx.enemy.name} "
                    f"({ctx.candidate.axis(Axis.ATTACK_RANGE)} vs {ctx.enemy.axis(Axis.ATTACK_RANGE)}) "
                    f"y {ctx.enemy.name} no tiene un reposicionamiento propio real disponible en esta fase, "
                    "lo que castiga su acceso al objetivo."
                ),
                premises=(
                    FactRef(f"{ctx.candidate.id}.axes.attack_range", ctx.candidate.axis(Axis.ATTACK_RANGE)),
                    FactRef(f"{ctx.enemy.id}.axes.attack_range", ctx.enemy.axis(Axis.ATTACK_RANGE)),
                ),
                condition="mientras se conserve el espacio y no se reciba control duro de cierre de distancia",
            )
        ]


class PokeVsSustainRule(Rule):
    """Poke sostenido por HEAL estructural vs. sustain rival que licua el poke.

    No trata a un campeón como "identidad de poke" por una etiqueta
    global: inspecciona qué habilidades disponibles en la fase tienen
    `tactical_uses` con `POKE`, sean o no el foco central del kit.
    """

    id = "G02"
    summary = "Un poke respaldado por curación estructural sostiene la lane; el sustain rival erosiona el valor del poke."
    category = "poke_vs_sustain"
    categories = frozenset({"poke_vs_sustain"})
    phases = frozenset({Phase.EARLY_LANE, Phase.FIRST_ITEM})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        poke_abilities = [a for a in ctx.candidate_abilities() if TacticalUse.POKE in a.tactical_uses]
        if not poke_abilities:
            return []

        effects: list[RuleEffect] = []
        for ability in poke_abilities:
            heals = ability.effects_of(EffectType.HEAL)
            if not heals:
                continue
            magnitude = max(e.magnitude for e in heals)
            effects.append(
                RuleEffect(
                    factor=Factor.LANE_PATTERN,
                    polarity=Polarity.PRO,
                    delta=0.08 * magnitude / 4,
                    text=(
                        f"{ability.name} de {ctx.candidate.name} no solo pokea: también lo cura al conectar "
                        "bajo condición, lo que sostiene su presencia en la lane más allá de un poke puro."
                    ),
                    premises=(_fact(ctx.candidate.id, ability.slot, EffectType.HEAL, magnitude),),
                )
            )

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


class DamageTypeAndShieldRule(Rule):
    """Tres consideraciones sobre daño y su mitigación, separadas y explícitas:

      1. El daño verdadero ignora resistencias (`true_damage_value`) — solo
         si la habilidad que lo porta está disponible en la fase actual.
      2. Un escudo común puede absorber CUALQUIER daño, verdadero incluido
         — tener daño verdadero no implica atravesar escudos
         (`shield_mitigation`). Una habilidad futura podría declarar
         `bypasses_shields=True` explícitamente; ninguna de este hito lo hace.
      3. La penetración (mágica o de armadura) conserva valor de daño
         contra durabilidad acumulada (`penetration_value`).
    """

    id = "G03"
    summary = "El daño verdadero ignora resistencias, pero un escudo puede absorberlo igual; la penetración conserva valor contra la durabilidad."
    categories = frozenset({"true_damage_value", "shield_mitigation", "penetration_value"})
    category = "true_damage_value"

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []

        for ability in ctx.candidate_abilities():
            for effect in ability.effects_of(EffectType.DAMAGE):
                if effect.damage_type != DamageType.TRUE:
                    continue
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.PRO,
                        delta=0.1 * effect.magnitude / 4,
                        text=(
                            f"El componente de daño verdadero de {ability.name} de {ctx.candidate.name} ignora "
                            f"resistencias acumuladas por {ctx.enemy.name}, por definición del tipo de daño."
                        ),
                        premises=(_fact(ctx.candidate.id, ability.slot, EffectType.DAMAGE, effect.damage_type.value),),
                        category="true_damage_value",
                    )
                )
            for effect in ability.effects_of(EffectType.MAGIC_PENETRATION) + ability.effects_of(EffectType.ARMOR_PENETRATION):
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.PRO,
                        delta=0.06 * effect.magnitude / 4 if effect.magnitude else 0.02,
                        text=(
                            f"{ability.name} de {ctx.candidate.name} penetra parte de la resistencia de "
                            f"{ctx.enemy.name}, conservando valor de daño contra su durabilidad acumulada."
                        ),
                        premises=(_fact(ctx.candidate.id, ability.slot, effect.type, effect.magnitude),),
                        category="penetration_value",
                    )
                )

        candidate_damage_types = {
            effect.damage_type
            for ability in ctx.candidate_abilities()
            for effect in ability.effects_of(EffectType.DAMAGE)
            if effect.damage_type is not None
        }
        if candidate_damage_types:
            for ability in ctx.enemy_abilities():
                shields = [e for e in ability.effects if e.type == EffectType.SHIELD_FROM_STORED]
                if not shields:
                    continue
                magnitude = max(e.magnitude for e in shields)
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.CONTRA,
                        delta=0.06 * magnitude / 4,
                        text=(
                            f"{ability.name} de {ctx.enemy.name} puede absorber parte del daño de "
                            f"{ctx.candidate.name}, incluido cualquier componente de daño verdadero: un escudo "
                            "común absorbe todo tipo de daño salvo que una habilidad concreta declare "
                            "explícitamente que lo ignora, y ninguna lo hace en esta base de conocimiento."
                        ),
                        premises=(_fact(ctx.enemy.id, ability.slot, EffectType.SHIELD_FROM_STORED, magnitude),),
                        condition="el efecto depende de cuánto escudo haya disponible en el momento del impacto",
                        category="shield_mitigation",
                    )
                )

        enemy_damage_types = {
            effect.damage_type
            for ability in ctx.enemy_abilities()
            for effect in ability.effects_of(EffectType.DAMAGE)
            if effect.damage_type is not None
        }
        if enemy_damage_types:
            for ability in ctx.candidate_abilities():
                shields = [e for e in ability.effects if e.type == EffectType.SHIELD_FROM_STORED]
                if not shields:
                    continue
                magnitude = max(e.magnitude for e in shields)
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.PRO,
                        delta=0.06 * magnitude / 4,
                        text=(
                            f"{ability.name} de {ctx.candidate.name} puede absorber parte del daño de "
                            f"{ctx.enemy.name}, incluido cualquier componente de daño verdadero que traiga."
                        ),
                        premises=(_fact(ctx.candidate.id, ability.slot, EffectType.SHIELD_FROM_STORED, magnitude),),
                        condition="el efecto depende de cuánto escudo haya disponible en el momento del impacto",
                        category="shield_mitigation",
                    )
                )
        return effects


class MitigationAndDisruptionRule(Rule):
    """Dos formas distintas de negar valor rival — nunca "niega" en absoluto:

      1. `damage_mitigation`: un escudo acumulable mitiga PARCIALMENTE un
         plan de intercambio sostenido/extendido. No elimina cargas de
         acumulación ya aplicadas.
      2. `mechanic_disruption`: una interrupción real puede negar un
         intento puntual de aplicación de stack rival (no el kit entero).
    """

    id = "G04"
    summary = "Un escudo acumulable mitiga parcialmente un plan de intercambio sostenido; una interrupción puede negar una aplicación de stack puntual."
    categories = frozenset({"damage_mitigation", "mechanic_disruption"})
    category = "damage_mitigation"

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []

        candidate_is_sustained = any(
            a.tactical_uses & _SUSTAINED_QUALIFYING_USES for a in ctx.candidate_abilities()
        )
        if candidate_is_sustained:
            for ability in ctx.enemy_abilities():
                shields = ability.effects_of(EffectType.SHIELD_FROM_STORED)
                if not shields:
                    continue
                has_heal_conversion = bool(ability.effects_of(EffectType.CONVERT_SHIELD_TO_HEAL))
                magnitude = max(e.magnitude for e in shields)
                delta = 0.08 * magnitude / 4 * (1.4 if has_heal_conversion else 1.0)
                extra = (
                    ", y además puede convertir el remanente en curación al reactivarse"
                    if has_heal_conversion
                    else ""
                )
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.CONTRA,
                        delta=delta,
                        text=(
                            f"{ability.name} de {ctx.enemy.name} acumula capacidad de absorción a partir del "
                            f"daño propio y recibido, lo que reduce parte del valor de un intercambio extendido "
                            f"de {ctx.candidate.name}{extra}. No elimina ni revierte cargas de acumulación ya "
                            "aplicadas."
                        ),
                        premises=(
                            _fact(ctx.enemy.id, ability.slot, EffectType.SHIELD_FROM_STORED, magnitude),
                            *(
                                (_fact(ctx.enemy.id, ability.slot, EffectType.CONVERT_SHIELD_TO_HEAL, True),)
                                if has_heal_conversion
                                else ()
                            ),
                        ),
                        condition="el efecto depende de cuánta capacidad de absorción se haya acumulado y del momento en que se active",
                        category="damage_mitigation",
                    )
                )

        for ability in ctx.candidate_abilities():
            if EffectType.INTERRUPT not in ability.effect_types():
                continue
            for enemy_ability in ctx.enemy_abilities():
                stack_apps = enemy_ability.effects_of(EffectType.STACK_APPLICATION)
                if not stack_apps:
                    continue
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.PRO,
                        delta=0.08,
                        text=(
                            f"{ability.name} de {ctx.candidate.name} puede interrumpir el intento de "
                            f"{enemy_ability.name} de {ctx.enemy.name} y negar esa aplicación puntual de "
                            "acumulación, no su mecánica de acumulación entera."
                        ),
                        premises=(
                            _fact(ctx.candidate.id, ability.slot, EffectType.INTERRUPT, True),
                            _fact(ctx.enemy.id, enemy_ability.slot, EffectType.STACK_APPLICATION, True),
                        ),
                        condition="depende de reaccionar a tiempo, antes de que el efecto rival se resuelva",
                        category="mechanic_disruption",
                    )
                )
                break  # una sola entrada por herramienta de interrupción, no una por cada habilidad rival que aplique stacks
        return effects


class IsolationRule(Rule):
    """Un aislamiento de duelo (`ISOLATE_DUEL`) NO puntúa por sí solo en
    esta V0: el contexto ya es un 1v1 puro, no se modelan aliados ni
    jungla, así que no hay "ayuda externa" que perder. Lo que sí puntúa,
    por separado, es el robo de estadísticas y la restricción del espacio
    del duelo — efectos con consecuencias dentro del propio 1v1 modelado.
    """

    id = "G05"
    summary = "El robo de estadísticas y la restricción de espacio de un aislamiento puntúan; la ausencia de ayuda externa no, porque esta V0 ya es un 1v1."
    categories = frozenset({"isolation_stat_steal", "isolation_arena"})
    category = "isolation_stat_steal"

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        for ability in ctx.enemy_abilities():
            types = ability.effect_types()

            if EffectType.ISOLATE_DUEL in types:
                # Deliberadamente sin RuleEffect: no hay ayuda externa que
                # perder en una consulta que ya modela un 1v1 puro. Se
                # referencia el efecto para dejar constancia de que fue
                # considerado y descartado a propósito, no ignorado por
                # omisión (ver docstring de esta clase).
                pass

            for effect in ability.effects_of(EffectType.STAT_STEAL):
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.CONTRA,
                        delta=0.1 * effect.magnitude / 4,
                        text=(
                            f"{ability.name} de {ctx.enemy.name} roba parte de las estadísticas de "
                            f"{ctx.candidate.name} mientras dura: una desventaja directa dentro del propio 1v1, "
                            "no una consecuencia de perder ayuda externa."
                        ),
                        premises=(_fact(ctx.enemy.id, ability.slot, EffectType.STAT_STEAL, effect.magnitude),),
                        category="isolation_stat_steal",
                    )
                )

            for effect in ability.effects_of(EffectType.RESTRICT_ARENA):
                available_space = ctx.candidate.axis(Axis.MOBILITY) + ctx.candidate.axis(Axis.DISENGAGE)
                if available_space > 1:
                    continue  # con suficiente movilidad/disengage, restringir el espacio no cambia demasiado
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.CONTRA,
                        delta=0.06 * effect.magnitude / 4,
                        text=(
                            f"{ability.name} de {ctx.enemy.name} restringe el espacio del duelo; "
                            f"{ctx.candidate.name} tiene poca movilidad o disengage para aprovechar cualquier "
                            "espacio adicional que hubiera tenido en la lane abierta."
                        ),
                        premises=(_fact(ctx.enemy.id, ability.slot, EffectType.RESTRICT_ARENA, effect.magnitude),),
                        condition="el efecto es mayor cuanto menor sea la movilidad/disengage disponible del candidato",
                        category="isolation_arena",
                    )
                )
        return effects


class EarlyPressureVsScalingRule(Rule):
    """Un campeón fuerte en early puede ser mejor en lane y peor en side lane tardía."""

    id = "G07"
    summary = "La presión temprana y el escalado tardío pueden favorecer a lados opuestos de la lane."
    category = "phase_transition"
    categories = frozenset({"phase_transition"})
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
    """Menor waveclear relega a defender la wave mientras el rival gana prioridad de rotación.

    Exige que la ventaja de waveclear del rival esté respaldada por una
    habilidad concreta disponible en la fase (`tactical_uses` con
    `WAVECLEAR`), no solo por el eje numérico.
    """

    id = "G08"
    summary = "Una brecha de waveclear respaldada por una habilidad concreta cede prioridad de mapa en el side lane tardío."
    category = "waveclear"
    categories = frozenset({"waveclear"})
    phases = _SIDE_ONLY

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        diff = ctx.enemy.axis(Axis.WAVECLEAR) - ctx.candidate.axis(Axis.WAVECLEAR)
        if diff < 2:
            return []
        enemy_waveclear_tools = [a for a in ctx.enemy_abilities() if TacticalUse.WAVECLEAR in a.tactical_uses]
        if not enemy_waveclear_tools:
            return []
        return [
            RuleEffect(
                factor=Factor.SCALING_SIDELANE,
                polarity=Polarity.CONTRA,
                delta=0.1 * diff,
                text=(
                    f"{ctx.candidate.name} tiene menos waveclear que {ctx.enemy.name}, respaldado por "
                    f"{enemy_waveclear_tools[0].name}, lo que lo relega a defender la wave mientras el rival "
                    "gana prioridad para rotar o presionar otra línea."
                ),
                premises=(
                    FactRef(f"{ctx.candidate.id}.axes.waveclear", ctx.candidate.axis(Axis.WAVECLEAR)),
                    FactRef(f"{ctx.enemy.id}.axes.waveclear", ctx.enemy.axis(Axis.WAVECLEAR)),
                ),
            )
        ]


class AbilityRelianceReliabilityRule(Rule):
    """Un matchup favorable puede seguir siendo poco confiable si exige ejecución precisa."""

    id = "G09"
    summary = "Alta dependencia de una habilidad clave hace que la ventaja sea condicional a acertarla."
    category = "ability_reliance"
    categories = frozenset({"ability_reliance"})
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
    categories = frozenset({"execution_demand"})
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
    categories = frozenset({"all_in_readiness"})
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


class ResourceAttritionRule(Rule):
    """Un poke repetible sin coste de maná tiene una limitación de recurso
    distinta a la de un kit que sí paga maná — pero sigue limitado por
    cooldown y por acertar la habilidad, nunca es un recurso infinito."""

    id = "G13"
    summary = "Un poke sin coste de maná se sostiene de forma distinta, aunque sigue limitado por cooldown y acierto."
    category = "resource_attrition"
    categories = frozenset({"resource_attrition"})
    phases = frozenset({Phase.EARLY_LANE, Phase.FIRST_ITEM})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        from lol_reasoner.domain.enums import ResourceType

        if ctx.candidate.casting_resource != ResourceType.RESOURCELESS:
            return []
        poke_abilities = [a for a in ctx.candidate_abilities() if TacticalUse.POKE in a.tactical_uses]
        if not poke_abilities:
            return []
        ability = poke_abilities[0]
        return [
            RuleEffect(
                factor=Factor.LANE_PATTERN,
                polarity=Polarity.CONDITIONAL,
                delta=0.1,
                text=(
                    f"{ctx.candidate.name} puede repetir {ability.name} sin gastar un recurso de lanzamiento "
                    "tradicional, lo que sostiene su poke más allá de lo que permitiría un presupuesto de maná."
                ),
                premises=(FactRef(f"{ctx.candidate.id}.casting_resource", ctx.candidate.casting_resource.value),),
                condition="sigue limitado por el cooldown de la habilidad y por acertarla: no es daño infinito",
                invalidated_if="esta V0 no modela cooldowns reales en segundos ni la precisión efectiva del jugador",
            )
        ]


class SpikeAlignmentRule(Rule):
    """Compara los power spikes declarados por fase entre ambos lados."""

    id = "G14"
    summary = "Compara la magnitud del power spike declarado de cada lado en la misma fase."
    category = "spike_alignment"
    categories = frozenset({"spike_alignment"})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        candidate_spike = next((s for s in ctx.candidate.spikes if s.phase == ctx.phase), None)
        enemy_spike = next((s for s in ctx.enemy.spikes if s.phase == ctx.phase), None)
        if candidate_spike is None or enemy_spike is None:
            return []
        diff = candidate_spike.magnitude - enemy_spike.magnitude
        if diff == 0:
            return []
        polarity = Polarity.PRO if diff > 0 else Polarity.CONTRA
        return [
            RuleEffect(
                factor=Factor.POWER_SPIKES,
                polarity=polarity,
                delta=0.08 * abs(diff),
                text=(
                    f"En esta fase, el power spike declarado de {ctx.candidate.name} (magnitud "
                    f"{candidate_spike.magnitude}: {candidate_spike.reason}) "
                    f"{'supera' if diff > 0 else 'queda por debajo de'} el de {ctx.enemy.name} (magnitud "
                    f"{enemy_spike.magnitude}: {enemy_spike.reason})."
                ),
                premises=(
                    FactRef(f"{ctx.candidate.id}.spikes.{ctx.phase.value}", candidate_spike.magnitude),
                    FactRef(f"{ctx.enemy.id}.spikes.{ctx.phase.value}", enemy_spike.magnitude),
                ),
            )
        ]


class DisplacementVsMobilityRule(Rule):
    """Desplazamiento del ENEMIGO (no self-dash) vs. su movilidad/disengage.

    Agrupa DISPLACE_ENEMY + BRIEF_CC + INTERRUPT de una misma habilidad en
    una única RuleEffect (usa el máximo de sus magnitudes, no la suma) para
    no triple-puntuar el mismo momento de control. Un slow sin
    desplazamiento en la misma habilidad se evalúa aparte, en una segunda
    pasada que excluye explícitamente las habilidades ya contadas arriba.
    """

    id = "G15"
    summary = "Un desplazamiento del rival (agrupado con su control/interrupción como un único momento) niega el espacio que su movilidad le daría; un slow aislado hace lo mismo en menor medida."
    category = "displacement_control"
    categories = frozenset({"displacement_control"})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        enemy_can_leverage_space = ctx.enemy.axis(Axis.MOBILITY) >= 2 or ctx.enemy.axis(Axis.DISENGAGE) >= 2
        if not enemy_can_leverage_space:
            return []  # sin movilidad/disengage que negar, no hay ventaja marginal que reportar

        abilities_counted: set[str] = set()
        for ability in ctx.candidate_abilities():
            types = ability.effect_types()
            control_hit = types & _CONTROL_MOMENT_TYPES
            if EffectType.DISPLACE_ENEMY not in control_hit:
                continue
            if not (ability.tactical_uses & _DISPLACEMENT_QUALIFYING_USES):
                continue
            magnitude = max(e.magnitude for e in ability.effects if e.type in control_hit)
            abilities_counted.add(ability.slot)
            effects.append(
                RuleEffect(
                    factor=Factor.LANE_PATTERN,
                    polarity=Polarity.PRO,
                    delta=0.1 * magnitude / 4,
                    text=(
                        f"{ability.name} de {ctx.candidate.name} desplaza al rival y le niega el espacio que su "
                        f"movilidad le permitiría generar, agrupando en un único momento de control: "
                        f"{', '.join(sorted(t.value for t in control_hit))}."
                    ),
                    premises=tuple(_fact(ctx.candidate.id, ability.slot, t, True) for t in sorted(control_hit, key=lambda t: t.value)),
                    category="displacement_control",
                )
            )

        for ability in ctx.candidate_abilities():
            if ability.slot in abilities_counted:
                continue  # ya contado como parte del "momento de control" de arriba
            slows = ability.effects_of(EffectType.SLOW)
            if not slows:
                continue
            magnitude = max(e.magnitude for e in slows)
            effects.append(
                RuleEffect(
                    factor=Factor.LANE_PATTERN,
                    polarity=Polarity.PRO,
                    delta=0.06 * magnitude / 4,
                    text=f"{ability.name} de {ctx.candidate.name} ralentiza y reduce el espacio que {ctx.enemy.name} podría generar.",
                    premises=(_fact(ctx.candidate.id, ability.slot, EffectType.SLOW, magnitude),),
                    category="displacement_control",
                )
            )
        return effects


GENERAL_RULES: tuple[Rule, ...] = (
    RangeAccessRule(),
    PokeVsSustainRule(),
    DamageTypeAndShieldRule(),
    MitigationAndDisruptionRule(),
    IsolationRule(),
    EarlyPressureVsScalingRule(),
    WaveclearGatingRule(),
    AbilityRelianceReliabilityRule(),
    ExecutionDemandBaselineRule(),
    AllInFragilityRule(),
    ResourceAttritionRule(),
    SpikeAlignmentRule(),
    DisplacementVsMobilityRule(),
)
