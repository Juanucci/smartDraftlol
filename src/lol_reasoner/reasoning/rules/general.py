"""Reglas generales de interacción mecánica — v1.6.1.

RESTRICCIÓN DURA (verificada por tests/test_no_hardcoded_pairs.py):
ninguna regla de este archivo puede comparar el `.id` de un campeón
contra un literal. Leer `.name` para armar texto legible sí está
permitido. Las reglas operan sobre `axes`, `casting_resource` y, sobre
todo, sobre `effects`/`tactical_uses` de las habilidades disponibles en
la fase actual (vía `ctx.candidate_abilities()` / `ctx.enemy_abilities()`
— nunca `champion.abilities` directo).

RECIPROCIDAD. Una interacción mecánica DIRECTA y COMPARTIDA debe poder
aparecer con polaridad correspondiente sea quien sea el candidato. El
hito 1.6 corrigió cuatro reglas basadas en ejes, pero la auditoría de
v1.6.1 encontró que dentro de la ex-G03 sobrevivían tres escaneos
unidireccionales: el daño verdadero y la penetración solo se buscaban en
`ctx.candidate_abilities()` (así que el remate de daño verdadero del
rival no figuraba como riesgo de nadie), y la mitigación de un plan
sostenido solo se buscaba en `ctx.enemy_abilities()` (así que el MISMO
escudo valía 0.045 como ventaja propia y 0.084 como penalización ajena).
La forma que evita reincidir es estructural, no de disciplina: cada
submétodo recibe `owner`/`owner_abilities` y se invoca dos veces, una
por dueño, con la MISMA fórmula de magnitud — nunca ramas separadas por
dirección.

ANTI-DOBLE-CONTEO. `causal_key` identifica la fuente mecánica exacta
(`dueño:slot:efecto`). Toda entrada que pueda puntuar lo lleva, y también
las observaciones sin score que representan un hecho compartido
deduplicable, para que no inflen contradicciones ni condiciones al
repetirse por fase. El scoring, el narrador y el cálculo de
contradicciones leen la vista causal (`trace.deduped_for_scoring`); la
traza cruda se conserva completa para auditoría.

CERTEZA Y PROCEDENCIA (v1.6.1). `Support` separa "cuánta certeza hay"
de "hacia dónde se inclina" (`Polarity`) y de "de qué depende"
(`condition`/`ConditionKind`). `Provenance` marca si el hecho se derivó
del kit o si es un prior editorial de un eje escrito a mano.

Guardrail de complejidad (registry.py): el tope de cantidad de reglas es
BLANDO; lo que se verifica duro es que ninguna regla acumule más de tres
categorías y que toda entrada puntuable traiga `causal_key`. Fue el
tope duro de 15 el que motivó fusionar la mitigación dentro de la regla
de daño en el hito 1.6, y esa fusión es la que escondió la asimetría.
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
    Provenance,
    ResourceType,
    Support,
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
_PENETRATION_TYPES = (EffectType.MAGIC_PENETRATION, EffectType.ARMOR_PENETRATION)

# Un pull acerca al rival a quien lo castea (ver Effect.displacement_vector).
_PULL_TOWARD_SELF = "toward_self"


def _fact(champion_id: str, ability_slot: str, effect_type: EffectType, value: object) -> FactRef:
    """FactRef con convención uniforme: cita habilidad + tipo de efecto,
    lo que permite verificar comportamiento (tests/test_vocabulary_alive.py)
    sin depender de que el texto humano nombre el EffectType."""

    return FactRef(f"{champion_id}.abilities.{ability_slot}.effects.{effect_type.value}", value)


def _sides(ctx: ReasoningContext):
    """Los dos dueños posibles de un hecho, con la polaridad que le
    corresponde desde la perspectiva del candidato. Recorrer esto es lo
    que hace imposible escribir un submétodo unidireccional por descuido:
    la magnitud se calcula una sola vez, en un solo lugar, para ambos."""

    return (
        (ctx.candidate, ctx.candidate_abilities(), ctx.enemy, Polarity.PRO),
        (ctx.enemy, ctx.enemy_abilities(), ctx.candidate, Polarity.CONTRA),
    )


class RangeAccessRule(Rule):
    """El rango y el kite castigan a quien tiene poco acceso al objetivo.

    Bidireccional: si el CANDIDATO tiene más rango y el enemigo no puede
    cerrarlo con un reposicionamiento propio (`SELF_DASH`) → PRO. Si es
    el ENEMIGO el que tiene más rango y es el CANDIDATO quien no puede
    cerrarlo → CONTRA. Un efecto que desplaza al ENEMIGO (`DISPLACE_ENEMY`)
    no cuenta como acceso al objetivo para quien lo usa: solo `SELF_DASH`
    cierra distancia para uno mismo.
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
            condition_kind=ConditionKind.STRATEGIC,
            support=Support.CONDITIONED,
            # Misma brecha de rango en early y side lane: una sola causa.
            causal_key=f"{ahead.id}:axis:attack_range>{behind.id}",
        )


class TradeSustainRule(Rule):
    """Curación estructural DENTRO de un intercambio, derivada de efectos.

    v1.6.1 reemplaza a la vieja `PokeVsSustainRule`, que tenía dos
    problemas distintos:

      1. Leía `TacticalUse.POKE` y describía a un campeón cuerpo a cuerpo
         como si su Q fuera poke a distancia.
      2. Infería un CONTRA desde el eje editorial `axes.sustain >= 3` del
         rival. Ese umbral era un acantilado: mover ese eje un solo punto
         (2 -> 3) cambiaba el GlobalScore 2.76 puntos, doce veces la
         diferencia total entre los dos candidatos del par evaluado. Un
         número escrito a mano decidía el matchup.

    Ahora la regla solo mira efectos: una habilidad con `HEAL` cuyo uso
    táctico sea de intercambio (`TRADE_EXTEND`/`SUSTAIN`) sostiene a su
    dueño dentro del trade, bajo las condiciones que ese efecto declare.
    Bidireccional y con la misma fórmula de magnitud para ambos lados.

    El concepto de "sustain" no desaparece: deja de entrar como número
    editorial. Derivarlo de efectos reales (curación, escudo, condición,
    disponibilidad y frecuencia) queda en docs/backlog-v1.md. Para esta
    versión es preferible que la regla no puntúe a conservar una
    inferencia falsa.
    """

    id = "G02"
    summary = "Una curación estructural condicionada sostiene a su dueño dentro de un intercambio extendido; el otro lado la enfrenta como riesgo."
    category = "trade_sustain"
    categories = frozenset({"trade_sustain"})
    phases = frozenset({Phase.EARLY_LANE, Phase.FIRST_ITEM})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        for owner, owner_abilities, other, polarity in _sides(ctx):
            effects.extend(self._heal_in_trade(owner, owner_abilities, other, polarity))
        return effects

    @staticmethod
    def _heal_in_trade(owner, owner_abilities, other, polarity: Polarity) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        for ability in owner_abilities:
            heals = ability.effects_of(EffectType.HEAL)
            if not heals or not (ability.tactical_uses & _SUSTAINED_QUALIFYING_USES):
                continue
            best = max(heals, key=lambda e: e.magnitude)
            conditions = sorted(c.value for c in best.conditions)
            readable = ", ".join(c.replace("_", " ") for c in conditions)
            condition_text = (
                f"solo se cobra si {ability.name} conecta cumpliendo sus condiciones ({readable})"
                if conditions
                else f"solo se cobra si {ability.name} conecta"
            )
            if polarity == Polarity.PRO:
                text = (
                    f"{ability.name} de {owner.name} recupera vida dentro del propio intercambio cuando "
                    f"conecta bajo su condición, lo que sostiene un trade extendido contra {other.name}."
                )
            else:
                text = (
                    f"{ability.name} de {owner.name} le recupera vida dentro del intercambio cuando conecta "
                    f"bajo su condición, lo que erosiona el saldo de un trade extendido para {other.name}."
                )
            effects.append(
                RuleEffect(
                    factor=Factor.LANE_PATTERN,
                    polarity=polarity,
                    delta=0.09 * best.magnitude / 4,
                    text=text,
                    premises=(
                        _fact(owner.id, ability.slot, EffectType.HEAL, best.magnitude),
                        FactRef(f"{owner.id}.abilities.{ability.slot}.conditions", tuple(conditions)),
                    ),
                    condition=condition_text,
                    condition_kind=ConditionKind.EXECUTION,
                    support=Support.CONDITIONED,
                    causal_key=f"{owner.id}:{ability.slot}:{EffectType.HEAL.value}",
                )
            )
        return effects


class DamageVsResistancesRule(Rule):
    """Cuánto valor de daño sobrevive a la resistencia rival: daño
    verdadero y penetración, con la cadena de acumulación cuando existe.

    BIDIRECCIONAL (corrección de v1.6.1). Antes este escaneo miraba solo
    `ctx.candidate_abilities()`, así que un remate de daño verdadero del
    rival simplemente no existía en la evaluación: al consultar por el
    otro lado, su lista de riesgos no lo mencionaba en ninguna parte
    mientras su propia ventaja de escudo sí decía "incluido el daño
    verdadero". La amenaza se nombraba al pasar sin haberse registrado.

    CADENA CAUSAL ÚNICA. Cuando el efecto de daño declara `stack_scaling`,
    la habilidad no produce dos ventajas separadas ("hace daño verdadero"
    + "escala con cargas"): produce UNA sola entrada que explica la
    cadena completa — ignora resistencias por el tipo de daño, su valor
    crece con las cargas ya aplicadas, la recompensa de umbral la
    amplifica si está disponible, usarla con pocas cargas conserva el
    tipo de daño pero sacrifica buena parte del potencial, y un escudo
    común puede absorberla igual. Esa relación se cuenta una vez acá; la
    comparación de recompensas de acumulación vive en StackRaceRule y no
    vuelve a puntuar el mismo vínculo.
    """

    id = "G03"
    summary = "El daño verdadero ignora resistencias y la penetración conserva valor frente a durabilidad acumulada, para el lado que los tenga."
    categories = frozenset({"true_damage_value", "penetration_value"})
    category = "true_damage_value"

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        for owner, owner_abilities, other, polarity in _sides(ctx):
            effects.extend(self._true_damage(ctx, owner, owner_abilities, other, polarity))
            effects.extend(self._penetration(owner, owner_abilities, other, polarity))
        return effects

    def _true_damage(self, ctx, owner, owner_abilities, other, polarity: Polarity) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        for ability in owner_abilities:
            for effect in ability.effects_of(EffectType.DAMAGE):
                if effect.damage_type != DamageType.TRUE:
                    continue
                premises = [_fact(owner.id, ability.slot, EffectType.DAMAGE, effect.damage_type.value)]
                chain = self._stack_chain_clause(owner, ability, effect, premises)
                shield_note = self._shield_caveat(ctx, other)
                text = (
                    f"El componente de daño verdadero de {ability.name} de {owner.name} ignora las "
                    f"resistencias de {other.name} por definición del tipo de daño.{chain}{shield_note}"
                )
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=polarity,
                        delta=0.1 * effect.magnitude / 4,
                        text=text,
                        premises=tuple(premises),
                        condition=(
                            "el tipo de daño no depende de nada, pero su magnitud sí depende de cuántas "
                            "cargas se hayan aplicado antes de usarla"
                        )
                        if effect.stack_scaling
                        else None,
                        condition_kind=ConditionKind.STRATEGIC if effect.stack_scaling else None,
                        support=Support.STRUCTURAL,
                        category="true_damage_value",
                        causal_key=f"{owner.id}:{ability.slot}:damage:true",
                    )
                )
        return effects

    @staticmethod
    def _stack_chain_clause(owner, ability, effect, premises: list[FactRef]) -> str:
        """La relación acumulación -> potencia de ESTA habilidad, citada
        una sola vez y desde el propio efecto que escala."""

        if not effect.stack_scaling:
            return ""
        mechanic = next((m for m in owner.stacking_mechanics if m.id == effect.stack_scaling), None)
        if mechanic is None:
            return ""
        premises.append(FactRef(f"{owner.id}.abilities.{ability.slot}.effects.damage.stack_scaling", mechanic.id))
        premises.append(FactRef(f"{owner.id}.stacking.{mechanic.id}.threshold", mechanic.threshold))
        amplified = any(
            e.type == EffectType.AMPLIFY_ABILITY and e.amplifies_slot == ability.slot
            for e in mechanic.reward_effects
        )
        reward_clause = ""
        if amplified:
            premises.append(
                FactRef(f"{owner.id}.stacking.{mechanic.id}.reward.amplifies_slot", ability.slot)
            )
            reward_clause = f" y alcanzar {mechanic.reward_name} la amplifica todavía más"
        return (
            f" Su valor crece con las cargas de {mechanic.name} ya aplicadas{reward_clause}: usarla con pocas "
            "cargas conserva el tipo de daño pero sacrifica buena parte de su potencial, así que tenerla "
            "disponible no implica que convenga usarla apenas se desbloquea."
        )

    @staticmethod
    def _shield_caveat(ctx, other) -> str:
        other_abilities = ctx.enemy_abilities() if other is ctx.enemy else ctx.candidate_abilities()
        has_shield = any(a.effects_of(EffectType.SHIELD_FROM_STORED) for a in other_abilities)
        if not has_shield:
            return ""
        return (
            f" Ignorar resistencias no es ignorar absorción: un escudo de {other.name} puede absorber este "
            "daño igual."
        )

    @staticmethod
    def _penetration(owner, owner_abilities, other, polarity: Polarity) -> list[RuleEffect]:
        """La penetración es una fortaleza REAL y se registra como tal
        (`STRUCTURAL`, ventaja de su dueño y riesgo del rival), pero con
        aporte efectivo CERO al score.

        Por qué cero y no una magnitud pequeña: la penetración física y la
        mágica compartían `magnitude: 1` en el KB y se cancelaban a
        `+0.015` contra `-0.015`, como si fueran equivalentes. Compartir un
        ordinal cualitativo no demuestra igual intensidad, ni igual
        disponibilidad, ni igual relevancia contra las resistencias
        concretas del rival. Cuantificar el impacto relativo exige valores
        numéricos comparables, escalado por nivel, las resistencias del
        objetivo y contexto de parche — nada de lo cual modela esta V0.

        No es `AMBIGUOUS`: que la penetración exista y beneficie a su dueño
        no tiene nada de ambiguo. Lo que no está calibrado es cuánto pesa.
        """

        effects: list[RuleEffect] = []
        for ability in owner_abilities:
            for effect_type in _PENETRATION_TYPES:
                for effect in ability.effects_of(effect_type):
                    resistance = (
                        "resistencia mágica"
                        if effect.type == EffectType.MAGIC_PENETRATION
                        else "armadura"
                    )
                    effects.append(
                        RuleEffect(
                            factor=Factor.MECHANICAL_INTERACTION,
                            polarity=polarity,
                            delta=0.0,
                            text=(
                                f"{ability.name} de {owner.name} penetra parte de la {resistance} de "
                                f"{other.name}, conservando valor de daño contra su durabilidad acumulada. "
                                f"Se registra como fortaleza real, pero sin mover el score: esta V0 no puede "
                                f"comparar la intensidad de una penetración contra la otra."
                            ),
                            premises=(_fact(owner.id, ability.slot, effect.type, effect.magnitude),),
                            support=Support.STRUCTURAL,
                            invalidated_if=(
                                "el impacto relativo de la penetración no está calibrado: haría falta valor "
                                "numérico, escalado por nivel, las resistencias concretas del objetivo y el "
                                "contexto de parche"
                            ),
                            category="penetration_value",
                            causal_key=f"{owner.id}:{ability.slot}:{effect.type.value}",
                        )
                    )
        return effects


class ShieldAbsorptionRule(Rule):
    """Un escudo acumulado absorbe daño — de cualquier tipo, incluido el
    verdadero — y puede convertir el remanente en curación.

    v1.6.1 corrige la asimetría numérica: la MISMA capacidad valía 0.045
    como ventaja de su dueño y 0.084 como penalización del rival, porque
    la variante "rica" (la que además mencionaba el plan sostenido y la
    conversión a curación) solo se calculaba escaneando al enemigo. Ahora
    hay una sola fórmula, dependiente solo del kit del dueño, evaluada
    dos veces con la misma magnitud y polaridad opuesta.

    La explicación se mantiene proporcional a lo que el escudo hace: si
    hay escudo acumulado y se activa a tiempo, absorbe parte del daño;
    puede convertir el remanente en curación; NO elimina cargas ya
    aplicadas, NO impide que se sigan acumulando, NO corta el intercambio
    y NO bloquea automáticamente un all-in. No se afirma que sea grande
    ni chico: no hay dato que lo justifique.
    """

    id = "G16"
    summary = "Un escudo construido a partir de daño acumulado absorbe parte del daño recibido, incluido el verdadero, sin eliminar cargas ni cortar el intercambio."
    category = "shield_mitigation"
    categories = frozenset({"shield_mitigation"})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        for owner, owner_abilities, other, polarity in _sides(ctx):
            other_abilities = ctx.enemy_abilities() if other is ctx.enemy else ctx.candidate_abilities()
            effects.extend(self._absorption(owner, owner_abilities, other, other_abilities, polarity))
        return effects

    @staticmethod
    def _absorption(owner, owner_abilities, other, other_abilities, polarity: Polarity) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        for ability in owner_abilities:
            shields = ability.effects_of(EffectType.SHIELD_FROM_STORED)
            if not shields:
                continue
            magnitude = max(e.magnitude for e in shields)
            converts = bool(ability.effects_of(EffectType.CONVERT_SHIELD_TO_HEAL))
            # Una sola fórmula, dependiente solo del kit del DUEÑO: la
            # magnitud no puede cambiar según quién haga la consulta.
            delta = 0.06 * magnitude / 4 + (0.02 if converts else 0.0)

            premises = [_fact(owner.id, ability.slot, EffectType.SHIELD_FROM_STORED, magnitude)]
            convert_clause = ""
            if converts:
                premises.append(_fact(owner.id, ability.slot, EffectType.CONVERT_SHIELD_TO_HEAL, True))
                convert_clause = " y puede convertir el remanente en curación al reactivarse"

            other_extends = any(a.tactical_uses & _SUSTAINED_QUALIFYING_USES for a in other_abilities)
            sustained_clause = (
                f" Contra un plan de intercambio extendido como el de {other.name}, eso resta parte del valor "
                "acumulado del trade."
                if other_extends
                else ""
            )
            text = (
                f"{ability.name} de {owner.name} absorbe parte del daño recibido —incluido el verdadero— si hay "
                f"escudo acumulado y se activa a tiempo{convert_clause}.{sustained_clause} No borra cargas ya "
                f"aplicadas ni impide que se sigan aplicando, y no bloquea por sí sola un all-in completo."
            )
            effects.append(
                RuleEffect(
                    factor=Factor.MECHANICAL_INTERACTION,
                    polarity=polarity,
                    delta=delta,
                    text=text,
                    premises=tuple(premises),
                    condition=(
                        "depende de cuánta capacidad de absorción se haya acumulado antes del impacto y del "
                        "momento en que se active"
                    ),
                    condition_kind=ConditionKind.STRATEGIC,
                    support=Support.CONDITIONED,
                    category="shield_mitigation",
                    causal_key=f"{owner.id}:{ability.slot}:{EffectType.SHIELD_FROM_STORED.value}",
                )
            )
        return effects


class SingleTargetConditionRule(Rule):
    """Daño aumentado cuando el impacto alcanza a UN SOLO enemigo.

    `ON_SINGLE_TARGET_HIT` significa exactamente eso: el impacto no se
    repartió con otras unidades. Los minions cuentan para negar el
    aumento — no es "sin otros campeones cerca", ni es `ISOLATE_DUEL`.

    Un aislamiento de duelo disponible en la fase facilita
    ESTRUCTURALMENTE cumplir la condición (dentro de esa zona no están
    las unidades normales de la línea), pero no la garantiza: la
    habilidad todavía tiene que acertarse. Por eso la entrada se inclina
    de forma pequeña y CONDITIONED en vez de quedarse muda o de afirmar
    una ventaja firme. El estado de la oleada no se modela en esta V0.
    """

    id = "G17"
    summary = "Un daño condicionado a impactar a un único enemigo se inclina levemente hacia su dueño, y más si un aislamiento retira las unidades de la línea."
    category = "single_target_bonus_damage"
    categories = frozenset({"single_target_bonus_damage"})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        for owner, owner_abilities, other, polarity in _sides(ctx):
            effects.extend(self._single_target(ctx, owner, owner_abilities, other, polarity))
        return effects

    def _single_target(self, ctx, owner, owner_abilities, other, polarity: Polarity) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        for ability in owner_abilities:
            damages = ability.effects_of(EffectType.DAMAGE)
            base = [e for e in damages if EffectCondition.ON_SINGLE_TARGET_HIT not in e.conditions]
            boosted = [e for e in damages if EffectCondition.ON_SINGLE_TARGET_HIT in e.conditions]
            if not (base and boosted):
                continue

            premises = [
                FactRef(f"{owner.id}.abilities.{ability.slot}.effects.damage.base", max(e.magnitude for e in base)),
                FactRef(f"{owner.id}.abilities.{ability.slot}.effects.damage.boosted", max(e.magnitude for e in boosted)),
                FactRef(f"{owner.id}.abilities.{ability.slot}.conditions.{EffectCondition.ON_SINGLE_TARGET_HIT.value}", True),
            ]
            isolation_note = self._isolation_clause(ctx, premises)

            if polarity == Polarity.PRO:
                text = (
                    f"{ability.name} de {owner.name} inflige más daño si el impacto alcanza a un único enemigo; "
                    f"golpear también minions u otras unidades niega ese aumento.{isolation_note}"
                )
            else:
                text = (
                    f"{ability.name} de {owner.name} inflige más daño si el impacto alcanza a un único enemigo, "
                    f"y {other.name} recibe ese aumento cuando no hay minions ni otras unidades repartiendo el "
                    f"impacto.{isolation_note}"
                )
            effects.append(
                RuleEffect(
                    factor=Factor.MECHANICAL_INTERACTION,
                    polarity=polarity,
                    delta=0.04,
                    text=text,
                    premises=tuple(premises),
                    condition=(
                        "depende de que el impacto no se reparta con minions u otras unidades, y la habilidad "
                        "todavía tiene que acertarse"
                    ),
                    condition_kind=ConditionKind.STRATEGIC,
                    support=Support.CONDITIONED,
                    invalidated_if="el estado de la oleada (minions presentes) no se modela en esta V0",
                    category="single_target_bonus_damage",
                    causal_key=f"{owner.id}:{ability.slot}:{EffectCondition.ON_SINGLE_TARGET_HIT.value}",
                )
            )
        return effects

    @staticmethod
    def _isolation_clause(ctx, premises: list[FactRef]) -> str:
        for champion, abilities in ((ctx.candidate, ctx.candidate_abilities()), (ctx.enemy, ctx.enemy_abilities())):
            ability = next((a for a in abilities if EffectType.ISOLATE_DUEL in a.effect_types()), None)
            if ability is None:
                continue
            premises.append(_fact(champion.id, ability.slot, EffectType.ISOLATE_DUEL, True))
            return (
                f" Dentro del aislamiento de {ability.name} de {champion.name} no están las unidades normales "
                "de la línea, así que la condición de único objetivo resulta más fácil de cumplir — aunque la "
                "habilidad todavía debe acertarse."
            )
        return ""


class IsolationRule(Rule):
    """Robo de estadísticas y restricción de espacio de un aislamiento —
    bidireccional según quién posee la habilidad. `ISOLATE_DUEL` NO
    puntúa por sí solo en esta V0: el contexto ya es un 1v1 puro
    (`pure_1v1`), no se modelan aliados ni jungla, así que no hay "ayuda
    externa" que perder.

    `restrict_arena` no es una ventaja automática para quien posee el
    aislamiento: es de doble filo. Favorece a su dueño al mantener al
    rival dentro de la zona, pero también puede facilitar que el lado que
    busca un intercambio extendido mantenga contacto y complete su propia
    mecánica de acumulación. Por eso queda `AMBIGUOUS`: aporta cero al
    score y se conserva entera en la explicación.
    """

    id = "G05"
    summary = "El robo de estadísticas de un aislamiento puntúa según quién lo posee; la restricción de espacio es de doble filo y la ausencia de ayuda externa no puntúa porque esta V0 ya es pure_1v1."
    categories = frozenset({"isolation_stat_steal", "isolation_arena"})
    category = "isolation_stat_steal"

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        for owner, owner_abilities, other, polarity in _sides(ctx):
            effects.extend(self._stat_steal(owner, owner_abilities, other, polarity))
            effects.extend(self._restrict_arena(ctx, owner, owner_abilities, other))
        return effects

    @staticmethod
    def _stat_steal(owner, owner_abilities, other, polarity: Polarity) -> list[RuleEffect]:
        effects = []
        for ability in owner_abilities:
            # ISOLATE_DUEL: deliberadamente sin RuleEffect propio (ver
            # docstring). Se referencia para dejar constancia de que fue
            # considerado a propósito; su consumidor real es G17.
            _ = EffectType.ISOLATE_DUEL in ability.effect_types()
            for effect in ability.effects_of(EffectType.STAT_STEAL):
                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=polarity,
                        delta=0.1 * effect.magnitude / 4,
                        text=(
                            f"{ability.name} de {owner.name} roba parte de las estadísticas de {other.name} "
                            "mientras dura: una consecuencia directa dentro del propio 1v1, no de perder ayuda "
                            "externa."
                        ),
                        premises=(_fact(owner.id, ability.slot, EffectType.STAT_STEAL, effect.magnitude),),
                        support=Support.STRUCTURAL,
                        category="isolation_stat_steal",
                        causal_key=f"{owner.id}:{ability.slot}:{EffectType.STAT_STEAL.value}",
                    )
                )
        return effects

    @staticmethod
    def _restrict_arena(ctx, owner, owner_abilities, other) -> list[RuleEffect]:
        """La geometría del aislamiento, no solo el robo de estadísticas.

        Restringir el espacio del duelo tiene consecuencias que van más
        allá de quién lo creó: cortar o espaciar el intercambio se vuelve
        más difícil PARA LOS DOS, el trade tiende a extenderse, no está la
        oleada para repartir un impacto que exige objetivo único, y ambos
        lados quedan más cerca de completar sus acumulaciones. Nada de eso
        favorece automáticamente a quien posee el aislamiento: la misma
        zona que sostiene su plan puede darle al otro el contacto que
        necesitaba.

        No se vuelve a puntuar "quitar ayuda externa": esta consulta ya
        representa un 1v1, así que no hay ayuda que quitar.
        """

        effects = []
        other_abilities = ctx.enemy_abilities() if other is ctx.enemy else ctx.candidate_abilities()
        for ability in owner_abilities:
            for effect in ability.effects_of(EffectType.RESTRICT_ARENA):
                premises = [_fact(owner.id, ability.slot, EffectType.RESTRICT_ARENA, effect.magnitude)]
                clauses = [
                    f"{ability.name} de {owner.name} restringe el espacio del duelo respecto de la lane abierta: "
                    f"con menos espacio, cortar o espaciar el intercambio se vuelve más difícil para los dos "
                    f"lados, y el trade tiende a extenderse."
                ]

                # Quién busca extender: puede ser cualquiera de los dos.
                extenders = [
                    champion.name
                    for champion, abilities in ((owner, owner_abilities), (other, other_abilities))
                    if any(a.tactical_uses & _SUSTAINED_QUALIFYING_USES for a in abilities)
                ]
                if extenders:
                    clauses.append(
                        f"Eso favorece a quien quiera sostener el contacto ({', '.join(extenders)}), no "
                        f"necesariamente a quien creó la zona."
                    )

                # Sin oleada, la condición de objetivo único es más fácil de cumplir.
                for champion, abilities in ((owner, owner_abilities), (other, other_abilities)):
                    single_target = next(
                        (
                            a
                            for a in abilities
                            if any(EffectCondition.ON_SINGLE_TARGET_HIT in e.conditions for e in a.effects)
                        ),
                        None,
                    )
                    if single_target is not None:
                        premises.append(
                            FactRef(
                                f"{champion.id}.abilities.{single_target.slot}.conditions."
                                f"{EffectCondition.ON_SINGLE_TARGET_HIT.value}",
                                True,
                            )
                        )
                        clauses.append(
                            f"Dentro de la zona no están las unidades normales de la línea, así que la condición "
                            f"de objetivo único de {single_target.name} de {champion.name} resulta más fácil de "
                            f"cumplir — sigue habiendo que acertarla."
                        )

                # Ambos pueden llegar a completar su acumulación.
                if owner.stacking_mechanics and other.stacking_mechanics:
                    owner_mech = owner.stacking_mechanics[0]
                    other_mech = other.stacking_mechanics[0]
                    premises.append(FactRef(f"{owner.id}.stacking.{owner_mech.id}.threshold", owner_mech.threshold))
                    premises.append(FactRef(f"{other.id}.stacking.{other_mech.id}.threshold", other_mech.threshold))
                    clauses.append(
                        f"Un intercambio que se extiende acerca a los dos a su recompensa: tanto {owner_mech.name} "
                        f"como {other_mech.name} pueden llegar a completarse."
                    )

                effects.append(
                    RuleEffect(
                        factor=Factor.MECHANICAL_INTERACTION,
                        polarity=Polarity.CONDITIONAL,
                        delta=0.04,
                        text=" ".join(clauses),
                        premises=tuple(premises),
                        condition=(
                            f"la geometría de la zona no favorece automáticamente a {owner.name}: qué lado "
                            f"aprovecha mejor un intercambio extendido y sin oleada es lo que decide el saldo"
                        ),
                        condition_kind=ConditionKind.STRATEGIC,
                        support=Support.CONDITIONED,
                        invalidated_if=(
                            "el estado de la oleada y la geometría real del terreno no se modelan en esta V0"
                        ),
                        category="isolation_arena",
                        causal_key=f"{owner.id}:{ability.slot}:{EffectType.RESTRICT_ARENA.value}",
                    )
                )
        return effects


class EditorialAxisPriorRule(Rule):
    """Presión temprana y escalado tardío: priors EDITORIALES, no
    conclusiones derivadas del kit.

    v1.6.1. `axes.early_pressure` y `axes.scaling` son valoraciones
    escritas a mano en el YAML. En el hito 1.6 producían entre el 40 % y
    el 64 % de todo el movimiento de score del motor, presentadas al
    consumidor como si fueran conclusiones mecánicas ("tiene más scaling
    que X, 4 vs 2"). Ahora:

      * ambas se marcan `Provenance.EDITORIAL_PRIOR`, lo que las pondera
        con el peso reducido de `config/weights.yaml` y las etiqueta
        explícitamente en el texto;
      * `scaling` NO mueve el score en absoluto (`CONDITIONAL`): esta V0
        no modela objetos, duración de partida ni teamfights, así que no
        tiene con qué derivar una comparación de escalado. Queda como
        dato descriptivo declarado;
      * `early_pressure` conserva una inclinación pequeña, porque la fase
        temprana sí está dentro de lo que el motor modela, pero acotada
        para que no vuelva a decidir el matchup sola.

    Los valores numéricos siguen en las premisas (auditables); el texto
    no los presenta como conclusión objetiva. Derivar estos ejes del kit
    está en docs/backlog-v1.md.
    """

    id = "G07"
    summary = "Los ejes editoriales de presión temprana y escalado se declaran como valoración manual: se etiquetan, pesan poco y el escalado no mueve el score."
    category = "editorial_axis_prior"
    categories = frozenset({"editorial_axis_prior"})
    phases = frozenset({Phase.EARLY_LANE, Phase.SIDE_LANE_LATE})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        if ctx.phase == Phase.EARLY_LANE:
            return self._prior(
                ctx,
                axis=Axis.EARLY_PRESSURE,
                factor=Factor.LANE_PATTERN,
                scores=True,
                condition=(
                    "es una valoración manual de la base de conocimiento sobre la fase temprana, no una "
                    "conclusión derivada de las habilidades modeladas"
                ),
            )
        if ctx.phase == Phase.SIDE_LANE_LATE:
            return self._prior(
                ctx,
                axis=Axis.SCALING,
                factor=Factor.SCALING_SIDELANE,
                scores=False,
                condition=(
                    "esta V0 no modela objetos, duración de partida ni combates de equipo: no puede derivar "
                    "una comparación de escalado, así que este dato no mueve el score"
                ),
            )
        return []

    @staticmethod
    def _prior(ctx, *, axis: Axis, factor: Factor, scores: bool, condition: str) -> list[RuleEffect]:
        diff = ctx.candidate.axis(axis) - ctx.enemy.axis(axis)
        if diff == 0:
            return []
        ahead, behind = (ctx.candidate, ctx.enemy) if diff > 0 else (ctx.enemy, ctx.candidate)
        polarity = (Polarity.PRO if diff > 0 else Polarity.CONTRA) if scores else Polarity.CONDITIONAL
        readable = axis.value.replace("_", " ")
        return [
            RuleEffect(
                factor=factor,
                polarity=polarity,
                delta=0.15 * abs(diff),
                text=(
                    f"La base de conocimiento estima a mano que {ahead.name} supera a {behind.name} en "
                    f"{readable}. Es una valoración editorial cargada en el YAML, no algo que el motor haya "
                    f"derivado de las habilidades modeladas"
                    + (
                        ". Se declara y se conserva en la traza, pero NO mueve el score: un eje escrito a mano "
                        "no puede decidir un veredicto mecánico."
                        if scores
                        else ", y no mueve el score."
                    )
                ),
                premises=(
                    FactRef(f"{ahead.id}.axes.{axis.value}", ahead.axis(axis)),
                    FactRef(f"{behind.id}.axes.{axis.value}", behind.axis(axis)),
                ),
                condition=condition,
                condition_kind=ConditionKind.STRATEGIC,
                support=Support.STRUCTURAL if scores else Support.AMBIGUOUS,
                provenance=Provenance.EDITORIAL_PRIOR,
                # Un mismo prior no puede multiplicarse por reaparecer en
                # varias fases: una causa, una contribución.
                causal_key=f"{ahead.id}:editorial_axis:{axis.value}>{behind.id}",
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
                _fact(ahead.id, tool.slot, EffectType.DAMAGE, tool.name),
            ),
            support=Support.CONDITIONED,
            condition="depende de que el side lane se juegue con prioridad de wave, no de un duelo directo",
            condition_kind=ConditionKind.STRATEGIC,
            causal_key=f"{ahead.id}:axis:waveclear>{behind.id}",
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
                    support=Support.AMBIGUOUS,
                    provenance=Provenance.EDITORIAL_PRIOR,
                    causal_key=f"{ctx.candidate.id}:editorial_axis:ability_reliance",
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
                    support=Support.AMBIGUOUS,
                    provenance=Provenance.EDITORIAL_PRIOR,
                    causal_key=f"{ctx.candidate.id}:editorial_axis:all_in_fragility",
                )
            ]
        return []


class ResourceAttritionRule(Rule):
    """Una habilidad repetible que no paga un recurso limitado.

    Es el consumidor real de `TacticalUse.POKE`, y deliberadamente NO
    convierte a nadie en "campeón de poke": describe una habilidad
    concreta, con su cooldown, su exposición y su necesidad de acertar. No
    puntúa mientras no se modelen cooldowns reales, acierto, secuencia ni
    estado de la oleada.
    """

    id = "G13"
    summary = "Una habilidad sin coste de recurso puede intentarse cada vez que esté disponible, pero sigue atada al cooldown, a la exposición y al acierto."
    category = "resource_attrition"
    categories = frozenset({"resource_attrition"})
    phases = frozenset({Phase.EARLY_LANE, Phase.FIRST_ITEM})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        for owner, owner_abilities, other, _polarity in _sides(ctx):
            effects.extend(self._resourceless(owner, owner_abilities, other))
        return effects

    @staticmethod
    def _resourceless(owner, owner_abilities, other) -> list[RuleEffect]:
        if owner.casting_resource != ResourceType.RESOURCELESS:
            return []
        repeatable = [a for a in owner_abilities if TacticalUse.POKE in a.tactical_uses]
        if not repeatable:
            return []
        ability = repeatable[0]
        punish_note = ""
        if other.axis(Axis.ALL_IN) >= 3 or other.axis(Axis.EARLY_PRESSURE) >= 3:
            punish_note = (
                f" Acercarse lo suficiente para lanzarla también expone a {owner.name} a que {other.name} "
                f"castigue esa aproximación."
            )
        return [
            RuleEffect(
                factor=Factor.LANE_PATTERN,
                polarity=Polarity.CONDITIONAL,
                delta=0.1,
                text=(
                    f"{ability.name} de {owner.name} no consume un recurso limitado como maná, así que "
                    f"{owner.name} puede intentar repetirla mientras esté disponible; su valor real sigue "
                    f"dependiendo del cooldown, de la exposición que exige y de acertarla.{punish_note}"
                ),
                premises=(
                    FactRef(f"{owner.id}.casting_resource", owner.casting_resource.value),
                    FactRef(f"{owner.id}.abilities.{ability.slot}.tactical_uses", TacticalUse.POKE.value),
                    FactRef(f"{other.id}.axes.all_in", other.axis(Axis.ALL_IN)),
                ),
                condition="sigue limitado por cooldown, exposición y acierto: no es daño repetible sin coste real",
                invalidated_if=(
                    "esta V0 no modela cooldowns en segundos, ni el acierto efectivo, ni la secuencia de "
                    "habilidades, ni el estado de la oleada"
                ),
                condition_kind=ConditionKind.EXECUTION,
                support=Support.AMBIGUOUS,
                category="resource_attrition",
                causal_key=f"{owner.id}:{ability.slot}:resource_attrition",
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
        for mover, mover_abilities, target, polarity in _sides(ctx):
            effects.extend(self._one_direction(mover, mover_abilities, target, polarity))
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
                    support=Support.STRUCTURAL,
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
                    support=Support.STRUCTURAL,
                    category="displacement_control",
                    causal_key=f"{mover.id}:{ability.slot}:{EffectType.SLOW.value}",
                )
            )
        return effects


class PullTowardEngageRule(Rule):
    """Atraer al rival hacia uno mismo: habilita la jugada propia y, a la
    vez, le da acceso a un duelista peligroso de corta distancia.

    Generalizable a cualquier pull futuro, no una excepción para un par:
    dispara cuando una habilidad tiene `DISPLACE_ENEMY` con
    `displacement_vector == "toward_self"` y el objetivo es una amenaza
    de corta distancia (all-in alto, movilidad baja) — exactamente el
    perfil al que acercarse le conviene.

    La conclusión es deliberadamente de DOBLE FILO y no se inclina:
    quién sale ganando de reducir la distancia depende de quién gane ese
    rango, que es la pregunta que el motor está tratando de responder.
    Afirmar una dirección sería circular. Por eso `Polarity.CONDITIONAL`
    (aporte cero) con `Support.CONDITIONED`, y toda la información útil
    en el texto y la condición.

    La cadena causal del pull se cuenta UNA vez: acercar + preparar la
    habilidad que combea + aportar una aplicación a la propia mecánica de
    acumulación son consecuencias del mismo casteo, no ventajas
    separadas; y comparte `causal_key` con `DisplacementVsMobilityRule`
    para que, si alguna vez disparan las dos sobre la misma habilidad, la
    vista causal las colapse.

    NO modela el uso invertido (castear el pull hacia atrás para
    alejarse): depende de la geometría del casteo, que esta V0 no
    representa. Queda en docs/backlog-v1.md como mecánica avanzada.
    """

    id = "G18"
    summary = "Atraer al rival hacia uno habilita el combo propio y a la vez le concede el rango que un duelista de corta distancia busca; el saldo depende de quién gane ese rango."
    category = "pull_engage_tradeoff"
    categories = frozenset({"pull_engage_tradeoff"})

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        effects: list[RuleEffect] = []
        for owner, owner_abilities, other, _polarity in _sides(ctx):
            effects.extend(self._pull(owner, owner_abilities, other))
        return effects

    @staticmethod
    def _is_short_range_threat(champion) -> bool:
        return champion.axis(Axis.ALL_IN) >= 3 and champion.axis(Axis.MOBILITY) <= 1

    def _pull(self, owner, owner_abilities, other) -> list[RuleEffect]:
        if not self._is_short_range_threat(other):
            return []
        effects: list[RuleEffect] = []
        for ability in owner_abilities:
            pulls = [
                e
                for e in ability.effects_of(EffectType.DISPLACE_ENEMY)
                if e.displacement_vector == _PULL_TOWARD_SELF
            ]
            if not pulls:
                continue
            magnitude = max(e.magnitude for e in pulls)
            premises = [
                FactRef(
                    f"{owner.id}.abilities.{ability.slot}.effects.displace_enemy.displacement_vector",
                    _PULL_TOWARD_SELF,
                ),
                FactRef(f"{other.id}.axes.all_in", other.axis(Axis.ALL_IN)),
                FactRef(f"{other.id}.axes.mobility", other.axis(Axis.MOBILITY)),
            ]
            # Misma cadena causal: el casteo que acerca también prepara lo
            # que combea y puede aportar una aplicación a la acumulación
            # propia. No son ventajas separadas.
            setup_clause = ""
            if TacticalUse.SETUP_COMBO in ability.tactical_uses:
                premises.append(
                    FactRef(f"{owner.id}.abilities.{ability.slot}.tactical_uses", TacticalUse.SETUP_COMBO.value)
                )
                setup_clause = f" El mismo casteo prepara el resto del combo de {owner.name}."
            stack_clause = ""
            stack_effects = ability.effects_of(EffectType.STACK_APPLICATION)
            if stack_effects:
                mechanic_id = next((e.feeds_stack for e in stack_effects if e.feeds_stack), None)
                mechanic = next((m for m in owner.stacking_mechanics if m.id == mechanic_id), None)
                if mechanic is not None:
                    premises.append(_fact(owner.id, ability.slot, EffectType.STACK_APPLICATION, mechanic.id))
                    stack_clause = f" y aporta una aplicación hacia {mechanic.name}"

            effects.append(
                RuleEffect(
                    factor=Factor.LANE_PATTERN,
                    polarity=Polarity.CONDITIONAL,
                    delta=0.03,
                    text=(
                        f"{ability.name} de {owner.name} atrae a {other.name} hacia {owner.name}{stack_clause}."
                        f"{setup_clause} Es de doble filo: {other.name} es una amenaza de corta distancia con "
                        f"all-in alto y poca movilidad, así que reducir la distancia también le entrega el rango "
                        f"en el que quiere pelear. Fallarla o usarla a destiempo cierra la ventana de "
                        f"intercambio en vez de abrirla."
                    ),
                    premises=tuple(premises),
                    condition=(
                        f"el saldo depende de quién gane el intercambio a corta distancia una vez cerrada la "
                        f"brecha, que es justamente lo que el resto del análisis intenta establecer"
                    ),
                    condition_kind=ConditionKind.STRATEGIC,
                    support=Support.CONDITIONED,
                    category="pull_engage_tradeoff",
                    # Compartido con G15: un mismo casteo, una sola causa.
                    causal_key=f"{owner.id}:{ability.slot}:{EffectType.DISPLACE_ENEMY.value}",
                )
            )
        return effects


GENERAL_RULES: tuple[Rule, ...] = (
    RangeAccessRule(),
    TradeSustainRule(),
    DamageVsResistancesRule(),
    ShieldAbsorptionRule(),
    SingleTargetConditionRule(),
    IsolationRule(),
    EditorialAxisPriorRule(),
    WaveclearGatingRule(),
    AbilityRelianceReliabilityRule(),
    AllInFragilityRule(),
    ResourceAttritionRule(),
    DisplacementVsMobilityRule(),
    PullTowardEngageRule(),
)
