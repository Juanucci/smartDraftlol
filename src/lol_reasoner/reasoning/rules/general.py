"""Reglas generales de interacción mecánica — hito 1.6.

RESTRICCIÓN DURA (verificada por tests/test_no_hardcoded_pairs.py):
ninguna regla de este archivo puede comparar el `.id` de un campeón
contra un literal. Leer `.name` para armar texto legible sí está
permitido. Las reglas operan sobre `axes`, `casting_resource` y, sobre
todo, sobre `effects`/`tactical_uses` de las habilidades disponibles en
la fase actual (vía `ctx.candidate_abilities()` / `ctx.enemy_abilities()`
— nunca `champion.abilities` directo).

Reciprocidad (hito 1.6, corrige un bug real encontrado en el hito
anterior): una interacción mecánica DIRECTA y COMPARTIDA — un mismo eje
enfrentado, o una habilidad de un lado contra una propiedad del otro —
debe poder aparecer con polaridad opuesta quien sea candidato. El bug
verificado en el hito 1.5: `RangeAccessRule`, `EarlyPressureVsScalingRule`,
`WaveclearGatingRule` y `DisplacementVsMobilityRule` solo implementaban
la mitad de la comparación (candidato favorecido → PRO), nunca la mitad
en la que el ENEMIGO está favorecido → CONTRA para el candidato. Las
cuatro quedan corregidas acá, calculando ambas direcciones dentro de un
mismo `evaluate(ctx)` (ambos campeones ya están disponibles en `ctx`,
no hace falta una "traza espejo"). `PokeVsSustainRule` NO tenía este bug:
no describe un hecho compartido con un dueño ambiguo, son dos preguntas
independientes por dirección (¿pokea el candidato? ¿tiene sustain el
enemigo?) que ya se recalculan correctamente solas al invertir.

Disciplina anti-doble-conteo: además de agrupar efectos de una misma
habilidad en una sola RuleEffect (ver `DisplacementVsMobilityRule`),
cuando dos causas DISTINTAS (misma regla en dos fases, o dos reglas
distintas) describen la MISMA fuente mecánica exacta, se les asigna el
mismo `causal_key` (`RuleEffect.causal_key`) para que
`ReasoningTrace.deduped_for_scoring` las colapse a una sola contribución
de score — la traza completa (todas las fases, todas las reglas) se
conserva íntegra para trazabilidad; lo que se deduplica es el CÁLCULO,
no la explicación disponible.

Guardrail temporal de esta V0 (documentado, revisable al incorporar los
otros ocho campeones): máximo 15 clases de regla general. Este archivo
más `stacking.py` suman 11.
"""

from __future__ import annotations

from lol_reasoner.domain.enums import (
    Axis,
    ConditionKind,
    DamageType,
    EffectCondition,
    EffectType,
    Factor,
    Phase,
    Polarity,
    ResourceType,
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
    """El rango y el kite castigan a quien tiene poco acceso al objetivo.

    Bidireccional: si el CANDIDATO tiene más rango y el enemigo no puede
    cerrarlo con un reposicionamiento propio (`SELF_DASH`) → PRO. Si es
    el ENEMIGO el que tiene más rango y es el CANDIDATO quien no puede
    cerrarlo → CONTRA. Un efecto que desplaza al ENEMIGO (`DISPLACE_ENEMY`,
    como Apprehend) no cuenta como acceso al objetivo para quien lo usa:
    solo `SELF_DASH` cierra distancia para uno mismo.
    """

    id = "G01"
    summary = "Una ventaja de rango, si el lado atrasado no puede cerrarla con un desplazamiento propio, castiga su acceso al objetivo."
    category = "range_access"
    categories = frozenset({"range_access"})
    phases = _LANE_PHASES

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        range_diff = ctx.candidate.axis(Axis.ATTACK_RANGE) - ctx.enemy.axis(Axis.ATTACK_RANGE)
        if range_diff >= 2 and not self._has_self_dash(ctx.enemy_abilities()):
            return [self._effect(ctx.candidate, ctx.enemy, range_diff, Polarity.PRO)]
        if range_diff <= -2 and not self._has_self_dash(ctx.candidate_abilities()):
            return [self._effect(ctx.enemy, ctx.candidate, -range_diff, Polarity.CONTRA)]
        return []

    @staticmethod
    def _has_self_dash(abilities) -> bool:
        return any(EffectType.SELF_DASH in a.effect_types() for a in abilities)

    def _effect(self, ahead, behind, diff: int, polarity: Polarity) -> RuleEffect:
        delta = min(0.6, 0.2 * diff)
        return RuleEffect(
            factor=Factor.LANE_PATTERN,
            polarity=polarity,
            delta=delta,
            text=(
                f"{ahead.name} tiene más rango de ataque que {behind.name} "
                f"({ahead.axis(Axis.ATTACK_RANGE)} vs {behind.axis(Axis.ATTACK_RANGE)}) "
                f"y {behind.name} no tiene un reposicionamiento propio real disponible en esta fase, "
                "lo que castiga su acceso al objetivo."
            ),
            premises=(
                FactRef(f"{ahead.id}.axes.attack_range", ahead.axis(Axis.ATTACK_RANGE)),
                FactRef(f"{behind.id}.axes.attack_range", behind.axis(Axis.ATTACK_RANGE)),
            ),
            condition="mientras se conserve el espacio y no se reciba control duro de cierre de distancia",
        )


class PokeVsSustainRule(Rule):
    """Poke sostenido por HEAL estructural vs. sustain rival que licua el poke.

    No trata a un campeón como "identidad de poke" por una etiqueta
    global: inspecciona qué habilidades disponibles en la fase tienen
    `tactical_uses` con `POKE`, sean o no el foco central del kit.

    No bidireccional por diseño: "mi poke me cura" y "el sustain rival
    licua mi poke" son dos preguntas independientes sobre herramientas
    propias, no un único hecho compartido con dueño ambiguo — se
    recalculan solas y correctamente al invertir candidato/enemigo.
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
                    condition_kind=ConditionKind.STRATEGIC,
                )
            )
        return effects


class DamageTypeAndShieldRule(Rule):
    """Daño, mitigación por escudo, y el matiz de "impacto único" — todo lo
    que gira en torno a cuánto valor conserva un daño frente a la
    resistencia/absorción rival. Cuatro consideraciones, cada una con su
    propio `causal_key` cuando corresponde:

      1. `true_damage_value`: el daño verdadero ignora resistencias —
         solo si la habilidad que lo porta está disponible en la fase.
      2. `penetration_value`: la penetración (mágica o de armadura)
         conserva valor de daño contra durabilidad acumulada.
      3. `shield_mitigation` + `damage_mitigation`: un escudo común
         puede absorber CUALQUIER daño (verdadero incluido) — tener
         daño verdadero no implica atravesar escudos. Cuando además el
         escudo mitiga específicamente un plan de intercambio sostenido
         (y puede convertir el remanente en curación), esa nota más
         rica comparte el `causal_key` del escudo genérico: es la MISMA
         capacidad de absorción explicada con dos matices, no dos
         ventajas independientes (se deduplica en scoring, ver
         `ReasoningTrace.deduped_for_scoring`). Ninguna habilidad de
         este hito declara `bypasses_shields=True`.
      4. `single_target_bonus_damage`: una habilidad con daño aumentado
         condicionado a `ON_SINGLE_TARGET_HIT` no puntúa (CONDITIONAL,
         delta no aplicado); se nombra el matiz de que estar dentro de
         un aislamiento de duelo (`ISOLATE_DUEL`, desde que esa
         habilidad esté disponible) facilita cumplir esa condición,
         sin asignarle todavía una ventaja numérica firme.
    """

    id = "G03"
    summary = "El daño verdadero ignora resistencias, pero un escudo puede absorberlo igual; la penetración conserva valor; un escudo acumulable mitiga parcialmente un plan sostenido."
    categories = frozenset({
        "true_damage_value",
        "penetration_value",
        "shield_mitigation",
        "damage_mitigation",
        "single_target_bonus_damage",
    })
    category = "true_damage_value"

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        effects.extend(self._true_damage_and_penetration(ctx))
        effects.extend(self._shield_mitigation(ctx, owner_abilities=ctx.enemy_abilities(), owner=ctx.enemy, victim=ctx.candidate, polarity=Polarity.CONTRA))
        effects.extend(self._shield_mitigation(ctx, owner_abilities=ctx.candidate_abilities(), owner=ctx.candidate, victim=ctx.enemy, polarity=Polarity.PRO))
        effects.extend(self._damage_mitigation_of_sustained_plan(ctx))
        effects.extend(self._single_target_bonus(ctx, owner_abilities=ctx.candidate_abilities(), owner=ctx.candidate))
        effects.extend(self._single_target_bonus(ctx, owner_abilities=ctx.enemy_abilities(), owner=ctx.enemy))
        return effects

    def _true_damage_and_penetration(self, ctx: ReasoningContext) -> list[RuleEffect]:
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
                        causal_key=f"{ctx.candidate.id}:{ability.slot}:damage:true",
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
                        causal_key=f"{ctx.candidate.id}:{ability.slot}:{effect.type.value}",
                    )
                )
        return effects

    def _shield_mitigation(self, ctx, *, owner_abilities, owner, victim, polarity: Polarity) -> list[RuleEffect]:
        victim_damage_types = {
            effect.damage_type
            for ability in (ctx.candidate_abilities() if victim is ctx.candidate else ctx.enemy_abilities())
            for effect in ability.effects_of(EffectType.DAMAGE)
            if effect.damage_type is not None
        }
        if not victim_damage_types:
            return []
        effects: list[RuleEffect] = []
        for ability in owner_abilities:
            shields = ability.effects_of(EffectType.SHIELD_FROM_STORED)
            if not shields:
                continue
            magnitude = max(e.magnitude for e in shields)
            if polarity == Polarity.CONTRA:
                text = (
                    f"{ability.name} de {owner.name} puede absorber parte del daño de {victim.name}, incluido "
                    "cualquier componente de daño verdadero: un escudo común absorbe todo tipo de daño salvo que "
                    "una habilidad concreta declare explícitamente que lo ignora, y ninguna lo hace en esta base "
                    "de conocimiento."
                )
            else:
                text = f"{ability.name} de {owner.name} puede absorber parte del daño de {victim.name}, incluido cualquier componente de daño verdadero que traiga."
            effects.append(
                RuleEffect(
                    factor=Factor.MECHANICAL_INTERACTION,
                    polarity=polarity,
                    delta=0.06 * magnitude / 4,
                    text=text,
                    premises=(_fact(owner.id, ability.slot, EffectType.SHIELD_FROM_STORED, magnitude),),
                    condition="el efecto depende de cuánto escudo haya disponible en el momento del impacto",
                    category="shield_mitigation",
                    causal_key=f"{owner.id}:{ability.slot}:{EffectType.SHIELD_FROM_STORED.value}",
                )
            )
        return effects

    def _damage_mitigation_of_sustained_plan(self, ctx: ReasoningContext) -> list[RuleEffect]:
        """El matiz específico: un escudo acumulable no solo absorbe daño
        genérico (ver `_shield_mitigation`), también mitiga en particular
        un plan de intercambio sostenido/extendido, y puede convertir el
        remanente en curación. Comparte `causal_key` con la entrada
        `shield_mitigation` CONTRA de la misma habilidad — es la MISMA
        capacidad, un matiz más rico, no una segunda ventaja."""

        candidate_is_sustained = any(a.tactical_uses & _SUSTAINED_QUALIFYING_USES for a in ctx.candidate_abilities())
        if not candidate_is_sustained:
            return []
        effects: list[RuleEffect] = []
        for ability in ctx.enemy_abilities():
            shields = ability.effects_of(EffectType.SHIELD_FROM_STORED)
            if not shields:
                continue
            has_heal_conversion = bool(ability.effects_of(EffectType.CONVERT_SHIELD_TO_HEAL))
            magnitude = max(e.magnitude for e in shields)
            delta = 0.08 * magnitude / 4 * (1.4 if has_heal_conversion else 1.0)
            extra = ", y además puede convertir el remanente en curación al reactivarse" if has_heal_conversion else ""
            effects.append(
                RuleEffect(
                    factor=Factor.MECHANICAL_INTERACTION,
                    polarity=Polarity.CONTRA,
                    delta=delta,
                    text=(
                        f"{ability.name} de {ctx.enemy.name} acumula capacidad de absorción a partir del daño "
                        f"propio y recibido, lo que reduce parte del valor de un intercambio extendido de "
                        f"{ctx.candidate.name}{extra}. No elimina ni revierte cargas de acumulación ya aplicadas, "
                        "ni corta el intercambio por sí sola: salir de él depende del posicionamiento y de otras "
                        "acciones."
                    ),
                    premises=(
                        _fact(ctx.enemy.id, ability.slot, EffectType.SHIELD_FROM_STORED, magnitude),
                        *((_fact(ctx.enemy.id, ability.slot, EffectType.CONVERT_SHIELD_TO_HEAL, True),) if has_heal_conversion else ()),
                    ),
                    condition="el efecto depende de cuánta capacidad de absorción se haya acumulado y del momento en que se active",
                    category="damage_mitigation",
                    causal_key=f"{ctx.enemy.id}:{ability.slot}:{EffectType.SHIELD_FROM_STORED.value}",
                )
            )
        return effects

    def _single_target_bonus(self, ctx: ReasoningContext, *, owner_abilities, owner) -> list[RuleEffect]:
        other = ctx.enemy if owner is ctx.candidate else ctx.candidate
        effects: list[RuleEffect] = []
        for ability in owner_abilities:
            damages = ability.effects_of(EffectType.DAMAGE)
            base = [e for e in damages if EffectCondition.ON_SINGLE_TARGET_HIT not in e.conditions]
            boosted = [e for e in damages if EffectCondition.ON_SINGLE_TARGET_HIT in e.conditions]
            if not (base and boosted):
                continue
            isolator = next(
                (c for c in (ctx.candidate, ctx.enemy) if any(EffectType.ISOLATE_DUEL in a.effect_types() for a in (ctx.candidate_abilities() if c is ctx.candidate else ctx.enemy_abilities()))),
                None,
            )
            isolation_note = ""
            if isolator is not None:
                isolation_note = (
                    f" Dentro del aislamiento de duelo de {isolator.name} no están las unidades normales de la "
                    "línea, por lo que resulta más sencillo cumplir la condición de único objetivo — aunque la "
                    "habilidad todavía debe acertarse."
                )
            if owner is ctx.candidate:
                text = (
                    f"{ability.name} de {owner.name} inflige más daño si el impacto alcanza a un único enemigo; "
                    f"golpear también minions u otras unidades niega ese aumento. El estado de la oleada no está "
                    f"modelado en esta V0.{isolation_note}"
                )
            else:
                text = (
                    f"{ability.name} de {owner.name} (rival) inflige más daño si el impacto alcanza a un único "
                    f"enemigo; {ctx.candidate.name} enfrenta ese riesgo reforzado cuando la oleada no está presente "
                    f"para absorberlo. El estado de la oleada no está modelado en esta V0.{isolation_note}"
                )
            premises = [
                FactRef(f"{owner.id}.abilities.{ability.slot}.effects.damage.base", max(e.magnitude for e in base)),
                FactRef(f"{owner.id}.abilities.{ability.slot}.effects.damage.boosted", max(e.magnitude for e in boosted)),
                FactRef(f"{owner.id}.abilities.{ability.slot}.conditions.{EffectCondition.ON_SINGLE_TARGET_HIT.value}", True),
            ]
            if isolator is not None:
                isolator_ability = next(
                    a for a in (ctx.candidate_abilities() if isolator is ctx.candidate else ctx.enemy_abilities())
                    if EffectType.ISOLATE_DUEL in a.effect_types()
                )
                premises.append(_fact(isolator.id, isolator_ability.slot, EffectType.ISOLATE_DUEL, True))
            effects.append(
                RuleEffect(
                    factor=Factor.MECHANICAL_INTERACTION,
                    polarity=Polarity.CONDITIONAL,
                    delta=0.05,
                    text=text,
                    premises=tuple(premises),
                    condition="depende de que el impacto no se reparta con minions u otras unidades",
                    invalidated_if="el estado de la oleada (minions presentes) no se modela en esta V0",
                    condition_kind=ConditionKind.STRATEGIC,
                    category="single_target_bonus_damage",
                    causal_key=f"{owner.id}:{ability.slot}:{EffectCondition.ON_SINGLE_TARGET_HIT.value}",
                )
            )
        return effects


class IsolationRule(Rule):
    """Robo de estadísticas y restricción de espacio de un aislamiento —
    bidireccional según quién posee la habilidad. `ISOLATE_DUEL` NO
    puntúa por sí solo en esta V0: el contexto ya es un 1v1 puro
    (`pure_1v1`), no se modelan aliados ni jungla, así que no hay "ayuda
    externa" que perder.

    `restrict_arena` no es una ventaja automática para quien posee el
    aislamiento: es de doble filo. Favorece a su dueño al mantener al
    rival dentro de la zona (acompañando el robo de estadísticas), pero
    también puede facilitar que el lado que busca un intercambio
    extendido (`TRADE_EXTEND`/`SUSTAIN`) mantenga contacto y complete su
    propia mecánica de acumulación. Por eso queda `CONDITIONAL`
    (`STRATEGIC`), citada en ambas direcciones, sin delta de score.
    """

    id = "G05"
    summary = "El robo de estadísticas de un aislamiento puntúa según quién lo posee; la restricción de espacio es de doble filo y la ausencia de ayuda externa no puntúa porque esta V0 ya es pure_1v1."
    categories = frozenset({"isolation_stat_steal", "isolation_arena"})
    category = "isolation_stat_steal"

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        effects.extend(self._stat_steal(ctx, owner_abilities=ctx.enemy_abilities(), owner=ctx.enemy, victim=ctx.candidate, polarity=Polarity.CONTRA))
        effects.extend(self._stat_steal(ctx, owner_abilities=ctx.candidate_abilities(), owner=ctx.candidate, victim=ctx.enemy, polarity=Polarity.PRO))
        effects.extend(self._restrict_arena(ctx, owner_abilities=ctx.enemy_abilities(), owner=ctx.enemy, other=ctx.candidate))
        effects.extend(self._restrict_arena(ctx, owner_abilities=ctx.candidate_abilities(), owner=ctx.candidate, other=ctx.enemy))
        return effects

    @staticmethod
    def _stat_steal(ctx, *, owner_abilities, owner, victim, polarity: Polarity) -> list[RuleEffect]:
        effects = []
        for ability in owner_abilities:
            # ISOLATE_DUEL: deliberadamente sin RuleEffect (ver docstring):
            # no hay ayuda externa que perder en pure_1v1. Se referencia
            # para dejar constancia de que fue considerado a propósito.
            _ = EffectType.ISOLATE_DUEL in ability.effect_types()
            for effect in ability.effects_of(EffectType.STAT_STEAL):
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=polarity,
                        delta=0.1 * effect.magnitude / 4,
                        text=(
                            f"{ability.name} de {owner.name} roba parte de las estadísticas de {victim.name} "
                            "mientras dura: una consecuencia directa dentro del propio 1v1, no de perder ayuda "
                            "externa."
                        ),
                        premises=(_fact(owner.id, ability.slot, EffectType.STAT_STEAL, effect.magnitude),),
                        category="isolation_stat_steal",
                        causal_key=f"{owner.id}:{ability.slot}:{EffectType.STAT_STEAL.value}",
                    )
                )
        return effects

    @staticmethod
    def _restrict_arena(ctx, *, owner_abilities, owner, other) -> list[RuleEffect]:
        effects = []
        for ability in owner_abilities:
            for effect in ability.effects_of(EffectType.RESTRICT_ARENA):
                other_extends = any(a.tactical_uses & _SUSTAINED_QUALIFYING_USES for a in (ctx.candidate_abilities() if other is ctx.candidate else ctx.enemy_abilities()))
                condition = (
                    f"favorece a {owner.name} al mantener a {other.name} dentro de la zona, acompañando el robo "
                    "de estadísticas"
                )
                if other_extends:
                    condition += (
                        f", pero también puede ayudar a {other.name} a mantener contacto y completar su propio "
                        "plan de intercambio extendido"
                    )
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.CONDITIONAL,
                        delta=0.04,
                        text=(
                            f"{ability.name} de {owner.name} restringe el espacio del duelo respecto de la lane "
                            "abierta: el efecto es de doble filo, no una ventaja automática."
                        ),
                        premises=(_fact(owner.id, ability.slot, EffectType.RESTRICT_ARENA, effect.magnitude),),
                        condition=condition,
                        condition_kind=ConditionKind.STRATEGIC,
                        category="isolation_arena",
                        causal_key=f"{owner.id}:{ability.slot}:{EffectType.RESTRICT_ARENA.value}",
                    )
                )
        return effects


class EarlyPressureVsScalingRule(Rule):
    """Presión temprana y escalado tardío pueden favorecer a lados opuestos
    de la lane. Bidireccional: el lado con más presión temprana recibe
    PRO en `early_lane` y el otro CONTRA (mismo hecho, polaridad
    correspondiente); simétrico para `scaling` en `side_lane_late`."""

    id = "G07"
    summary = "La presión temprana y el escalado tardío favorecen al lado con el eje más alto en esa fase; el otro lado recibe la contrapartida."
    category = "phase_transition"
    categories = frozenset({"phase_transition"})
    phases = frozenset({Phase.EARLY_LANE, Phase.SIDE_LANE_LATE})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        if ctx.phase == Phase.EARLY_LANE:
            return self._compare(ctx, axis=Axis.EARLY_PRESSURE, factor=Factor.LANE_PATTERN, condition=None, condition_kind=None)
        if ctx.phase == Phase.SIDE_LANE_LATE:
            return self._compare(
                ctx,
                axis=Axis.SCALING,
                factor=Factor.SCALING_SIDELANE,
                condition="depende de que la partida se extienda y de la ventaja de objetos acumulada",
                condition_kind=ConditionKind.STRATEGIC,
            )
        return []

    @staticmethod
    def _compare(ctx, *, axis: Axis, factor: Factor, condition, condition_kind) -> list[RuleEffect]:
        diff = ctx.candidate.axis(axis) - ctx.enemy.axis(axis)
        if diff == 0:
            return []
        polarity = Polarity.PRO if diff > 0 else Polarity.CONTRA
        ahead, behind = (ctx.candidate, ctx.enemy) if diff > 0 else (ctx.enemy, ctx.candidate)
        # Solo la entrada CONTRA (candidato atrasado) lleva `condition`:
        # es la que introduce la incertidumbre ("depende de que se
        # extienda..."); la entrada PRO simplemente reporta el hecho.
        effect_condition = condition if polarity == Polarity.CONTRA else None
        effect_condition_kind = condition_kind if effect_condition else None
        return [
            RuleEffect(
                factor=factor,
                polarity=polarity,
                delta=0.15 * abs(diff),
                text=(
                    f"{ahead.name} tiene más {axis.value.replace('_', ' ')} que {behind.name} "
                    f"({ahead.axis(axis)} vs {behind.axis(axis)})."
                ),
                premises=(
                    FactRef(f"{ahead.id}.axes.{axis.value}", ahead.axis(axis)),
                    FactRef(f"{behind.id}.axes.{axis.value}", behind.axis(axis)),
                ),
                condition=effect_condition,
                condition_kind=effect_condition_kind,
            )
        ]


class WaveclearGatingRule(Rule):
    """Menor waveclear relega a defender la wave mientras el rival gana
    prioridad de rotación. Bidireccional: si el CANDIDATO tiene más
    waveclear (respaldado por una habilidad concreta) → PRO; si es el
    ENEMIGO → CONTRA.
    """

    id = "G08"
    summary = "Una brecha de waveclear respaldada por una habilidad concreta cede prioridad de mapa en el side lane tardío, para cualquiera de los dos lados."
    category = "waveclear"
    categories = frozenset({"waveclear"})
    phases = _SIDE_ONLY

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        diff = ctx.candidate.axis(Axis.WAVECLEAR) - ctx.enemy.axis(Axis.WAVECLEAR)
        if diff >= 2 and self._has_waveclear_tool(ctx.candidate_abilities()):
            return [self._effect(ctx.candidate, ctx.candidate_abilities(), ctx.enemy, Polarity.PRO)]
        if diff <= -2 and self._has_waveclear_tool(ctx.enemy_abilities()):
            return [self._effect(ctx.enemy, ctx.enemy_abilities(), ctx.candidate, Polarity.CONTRA)]
        return []

    @staticmethod
    def _has_waveclear_tool(abilities) -> bool:
        return any(TacticalUse.WAVECLEAR in a.tactical_uses for a in abilities)

    @staticmethod
    def _effect(ahead, ahead_abilities, behind, polarity: Polarity) -> RuleEffect:
        tool = next(a for a in ahead_abilities if TacticalUse.WAVECLEAR in a.tactical_uses)
        diff = ahead.axis(Axis.WAVECLEAR) - behind.axis(Axis.WAVECLEAR)
        return RuleEffect(
            factor=Factor.SCALING_SIDELANE,
            polarity=polarity,
            delta=0.1 * diff,
            text=(
                f"{behind.name} tiene menos waveclear que {ahead.name}, respaldado por {tool.name}, lo que lo "
                "relega a defender la wave mientras el rival gana prioridad para rotar o presionar otra línea."
            ),
            premises=(
                FactRef(f"{behind.id}.axes.waveclear", behind.axis(Axis.WAVECLEAR)),
                FactRef(f"{ahead.id}.axes.waveclear", ahead.axis(Axis.WAVECLEAR)),
            ),
        )


class AbilityRelianceReliabilityRule(Rule):
    """Un matchup favorable puede seguir siendo poco confiable si exige
    ejecución precisa. `EXECUTION`: sí puede subir `required_skill`."""

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
                    condition_kind=ConditionKind.EXECUTION,
                )
            ]
        return []


class AllInFragilityRule(Rule):
    """Un all-in fuerte pero con poca durabilidad sigue siendo una apuesta
    riesgosa. `STRATEGIC`: depende de ventaja previa/objetos, no de que
    el jugador ejecute mejor o peor."""

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
                    condition_kind=ConditionKind.STRATEGIC,
                )
            ]
        return []


class ResourceAttritionRule(Rule):
    """Un poke repetible sin coste de maná tiene una limitación de recurso
    distinta a la de un kit que sí paga maná — pero sigue limitado por
    cooldown, acierto, rango/exposición y el riesgo de que el rival
    castigue la aproximación. `EXECUTION`: acertar el poke a distancia
    es, ante todo, una cuestión de ejecución del jugador."""

    id = "G13"
    summary = "Un poke sin coste de maná se sostiene de forma distinta, pero sigue limitado por cooldown, acierto y el riesgo de exponerse."
    category = "resource_attrition"
    categories = frozenset({"resource_attrition"})
    phases = frozenset({Phase.EARLY_LANE, Phase.FIRST_ITEM})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        if ctx.candidate.casting_resource != ResourceType.RESOURCELESS:
            return []
        poke_abilities = [a for a in ctx.candidate_abilities() if TacticalUse.POKE in a.tactical_uses]
        if not poke_abilities:
            return []
        ability = poke_abilities[0]
        punish_note = ""
        if ctx.enemy.axis(Axis.ALL_IN) >= 3 or ctx.enemy.axis(Axis.EARLY_PRESSURE) >= 3:
            punish_note = f" Acercarse a poquear también expone a {ctx.candidate.name} a que {ctx.enemy.name} castigue esa aproximación."
        return [
            RuleEffect(
                factor=Factor.LANE_PATTERN,
                polarity=Polarity.CONDITIONAL,
                delta=0.1,
                text=(
                    f"{ctx.candidate.name} puede repetir {ability.name} sin gastar un recurso de lanzamiento "
                    f"tradicional, lo que sostiene su poke más allá de lo que permitiría un presupuesto de "
                    f"maná.{punish_note}"
                ),
                premises=(
                    FactRef(f"{ctx.candidate.id}.casting_resource", ctx.candidate.casting_resource.value),
                    FactRef(f"{ctx.enemy.id}.axes.all_in", ctx.enemy.axis(Axis.ALL_IN)),
                ),
                condition="sigue limitado por cooldown, rango/exposición y por acertarla: no es daño infinito",
                invalidated_if="esta V0 no modela cooldowns reales en segundos ni la precisión efectiva del jugador",
                condition_kind=ConditionKind.EXECUTION,
            )
        ]


class DisplacementVsMobilityRule(Rule):
    """Desplazamiento del ENEMIGO (no self-dash) vs. su movilidad/disengage.
    Bidireccional: se evalúa una vez con el candidato como quien
    desplaza (PRO) y otra con el enemigo como quien desplaza (CONTRA
    para el candidato) — la misma pregunta, dueño invertido.

    Agrupa DISPLACE_ENEMY + BRIEF_CC + INTERRUPT de una misma habilidad
    en una única RuleEffect (usa el máximo de sus magnitudes, no la
    suma) para no triple-puntuar el mismo momento de control. Un slow
    sin desplazamiento en la misma habilidad se evalúa aparte.
    """

    id = "G15"
    summary = "El desplazamiento del rival (agrupado con su control/interrupción) niega el espacio que su movilidad le daría, sea cual sea el dueño de la herramienta."
    category = "displacement_control"
    categories = frozenset({"displacement_control"})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        effects.extend(self._one_direction(ctx.candidate, ctx.candidate_abilities(), ctx.enemy, Polarity.PRO))
        effects.extend(self._one_direction(ctx.enemy, ctx.enemy_abilities(), ctx.candidate, Polarity.CONTRA))
        return effects

    def _one_direction(self, mover, mover_abilities, target, polarity: Polarity) -> list[RuleEffect]:
        target_can_leverage_space = target.axis(Axis.MOBILITY) >= 2 or target.axis(Axis.DISENGAGE) >= 2
        if not target_can_leverage_space:
            return []  # sin movilidad/disengage que negar, no hay ventaja marginal que reportar

        effects: list[RuleEffect] = []
        abilities_counted: set[str] = set()
        for ability in mover_abilities:
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
                    polarity=polarity,
                    delta=0.1 * magnitude / 4,
                    text=(
                        f"{ability.name} de {mover.name} desplaza a {target.name} y le niega el espacio que su "
                        f"movilidad le permitiría generar, agrupando en un único momento de control: "
                        f"{', '.join(sorted(t.value for t in control_hit))}."
                    ),
                    premises=tuple(_fact(mover.id, ability.slot, t, True) for t in sorted(control_hit, key=lambda t: t.value)),
                    category="displacement_control",
                    causal_key=f"{mover.id}:{ability.slot}:{EffectType.DISPLACE_ENEMY.value}",
                )
            )

        for ability in mover_abilities:
            if ability.slot in abilities_counted:
                continue  # ya contado como parte del "momento de control" de arriba
            slows = ability.effects_of(EffectType.SLOW)
            if not slows:
                continue
            magnitude = max(e.magnitude for e in slows)
            effects.append(
                RuleEffect(
                    factor=Factor.LANE_PATTERN,
                    polarity=polarity,
                    delta=0.06 * magnitude / 4,
                    text=f"{ability.name} de {mover.name} ralentiza a {target.name} y reduce el espacio que su movilidad podría generar.",
                    premises=(_fact(mover.id, ability.slot, EffectType.SLOW, magnitude),),
                    category="displacement_control",
                    causal_key=f"{mover.id}:{ability.slot}:{EffectType.SLOW.value}",
                )
            )
        return effects


GENERAL_RULES: tuple[Rule, ...] = (
    RangeAccessRule(),
    PokeVsSustainRule(),
    DamageTypeAndShieldRule(),
    IsolationRule(),
    EarlyPressureVsScalingRule(),
    WaveclearGatingRule(),
    AbilityRelianceReliabilityRule(),
    AllInFragilityRule(),
    ResourceAttritionRule(),
    DisplacementVsMobilityRule(),
)
