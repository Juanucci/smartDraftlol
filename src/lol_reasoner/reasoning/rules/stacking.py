"""G12 — StackRaceRule: la tensión genérica entre dos mecánicas de
acumulación (`StackingMechanic`), sin nombrar campeones.

Implementa el ejemplo central del brief:

    Mordekaiser busca tres impactos para activar Darkness Rise.
    Darius busca cinco cargas para activar Noxian Might y potenciar su R.
    Mordekaiser obtiene antes su primera recompensa de trade extendido.
    Continuar peleando después de activarla acerca a Darius a su
    recompensa más peligrosa.
    ...

Nada de esto se escribe a mano por campeón: se deriva de
`StackingMechanic.applied_by`/`threshold`/`stacks_per_application` y de
qué `Effect`s tienen las habilidades involucradas. La regla nunca lee
`champion.id` ni `champion.name` para decidir — solo para el texto.

Hito 1.6 — tres correcciones de honestidad:
  1. `_first_threshold_effect` pasa a `CONDITIONAL`: la fórmula
     (fuentes + aceleradores - aplicaciones necesarias) es un ORDEN
     ESTRUCTURAL, no una predicción de quién activa primero en el
     tiempo real de la partida (no modela cadencia, cooldowns, acierto
     ni secuencia). Separa "umbral menor" de "probabilidad real de
     activarlo primero".
  2. El reset de cooldown al remate (`COOLDOWN_RESET`) deja de sumar a
     la recompensa: en una consulta `pure_1v1` no hay un segundo
     objetivo sobre el que "perpetuar la amenaza".
  3. `_reward_magnitude_effect` reduce su delta y declara explícitamente
     que suma magnitudes ordinales de tipos heterogéneos — una
     aproximación cualitativa, no una equivalencia de unidades.

Se emiten tres `TraceEntry` separados y nunca opuestos dentro de uno
solo: (1) comparación estructural de umbral (con la nota de
acumulador/slow de ambos lados), (2) magnitud de recompensa si se
extiende, (3) la condición de extender-vs-cortar el intercambio.
"""

from __future__ import annotations

from lol_reasoner.domain.champion import Ability, Champion, StackingMechanic
from lol_reasoner.domain.enums import ConditionKind, EffectType, Factor, Phase, Polarity, TacticalUse, is_available_in
from lol_reasoner.reasoning.context import ReasoningContext
from lol_reasoner.reasoning.rules.base import Rule, RuleEffect
from lol_reasoner.reasoning.trace import FactRef

_ACCELERATOR_TYPES = frozenset({EffectType.AUTO_ATTACK_RESET, EffectType.EMPOWER_NEXT_ATTACK})

# Tipos de efecto reconocidos como contribuyentes a la magnitud de una
# recompensa de umbral. Dispatch explícito (en vez de sumar cualquier
# `effect.magnitude` a ciegas) para que quede citado en código cuál
# vocabulario alimenta esta cuenta. COOLDOWN_RESET deliberadamente NO
# está acá (ver docstring del módulo, punto 2).
_REWARD_CONTRIBUTING_TYPES = frozenset({
    EffectType.EMPOWER_SELF,
    EffectType.AMPLIFY_ABILITY,
    EffectType.AURA_DAMAGE,
    EffectType.MOVEMENT_SPEED,
})


def _fact(champion_id: str, ability_slot: str, effect_type: EffectType, value: object) -> FactRef:
    """Convención uniforme con general.py: cita habilidad + tipo de efecto."""

    return FactRef(f"{champion_id}.abilities.{ability_slot}.effects.{effect_type.value}", value)


def _abilities_in_phase(champion: Champion, phase: Phase) -> tuple[Ability, ...]:
    return tuple(a for a in champion.abilities if is_available_in(a.available_from, phase))


def accelerator_abilities(champion: Champion, mechanic: StackingMechanic, phase: Phase) -> tuple[Ability, ...]:
    """Habilidades YA DISPONIBLES en `phase` que aceleran la llegada al
    próximo golpe que aplica una carga (auto-reset o potenciación del
    próximo ataque). Se deriva escaneando efectos, no se declara a mano
    en el YAML — así un W como Crippling Strike no puede "duplicar" una
    carga: solo adelanta cuándo llega el próximo golpe que ya está
    contado en `applied_by`."""

    if "basic_attack" not in mechanic.applied_by:
        return ()
    return tuple(a for a in _abilities_in_phase(champion, phase) if a.effect_types() & _ACCELERATOR_TYPES)


def applications_needed(mechanic: StackingMechanic) -> int:
    return mechanic.applications_needed


def ramp_speed_rank(champion: Champion, mechanic: StackingMechanic, phase: Phase) -> int:
    """Ordinal cualitativo de "qué tan accesible es el umbral" — NUNCA una
    tasa real ni una estimación de segundos ni una predicción de quién
    activa primero. Solo sirve para comparar dos mecánicas entre sí:
    más fuentes + más aceleradores YA DISPONIBLES en `phase` + menos
    aplicaciones necesarias => rank más alto => umbral estructuralmente
    más accesible."""

    sources = len(mechanic.applied_by)
    accelerators = len(accelerator_abilities(champion, mechanic, phase))
    return sources + accelerators - applications_needed(mechanic)


def reward_magnitude(champion: Champion, mechanic: StackingMechanic, phase: Phase) -> int:
    """Magnitud agregada del beneficio de alcanzar el umbral, filtrada por
    fase: un efecto que amplifica un slot (`amplifies_slot`) solo cuenta
    si esa habilidad ya está disponible en `phase` (p. ej. la
    amplificación de Noxian Might sobre R no cuenta antes de level_6,
    aunque el propio umbral de 5 cargas sea alcanzable antes). No
    incluye `COOLDOWN_RESET`: en `pure_1v1` no hay un segundo objetivo
    sobre el que perpetuar la amenaza (el efecto sigue en el YAML para
    un futuro análisis 5v5, ver `ISOLATE_DUEL`/`COOLDOWN_RESET` en
    domain/enums.py)."""

    total = 0
    for effect in mechanic.reward_effects:
        if effect.type not in _REWARD_CONTRIBUTING_TYPES:
            continue
        if effect.amplifies_slot is not None:
            amplified = champion.ability(effect.amplifies_slot)
            if amplified is None or not is_available_in(amplified.available_from, phase):
                continue
        total += effect.magnitude

    # Además de la recompensa declarada al umbral, una habilidad ya
    # disponible puede escalar continuamente con el conteo actual de la
    # mecánica (p. ej. el propio daño de Noxian Guillotine escala con
    # las cargas de Hemorrhage ya aplicadas, no solo al llegar a 5).
    for ability in _abilities_in_phase(champion, phase):
        for effect in ability.effects:
            if effect.type == EffectType.AMPLIFY_ABILITY and effect.stack_scaling == mechanic.id:
                total += effect.magnitude

    return total


class StackRaceRule(Rule):
    """La tensión entre dos StackingMechanic enfrentadas. Ver docstring del
    módulo para los tres TraceEntry que produce."""

    id = "G12"
    summary = "Compara umbral estructural, aceleradores y recompensa de las StackingMechanic de ambos lados; el orden real de activación no se modela."
    categories = frozenset({"stack_race"})
    category = "stack_race"

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        if not ctx.candidate.stacking_mechanics or not ctx.enemy.stacking_mechanics:
            return []
        candidate_mechanic = ctx.candidate.stacking_mechanics[0]
        enemy_mechanic = ctx.enemy.stacking_mechanics[0]
        effects: list[RuleEffect] = []

        effects.extend(self._structural_threshold_effect(ctx, candidate_mechanic, enemy_mechanic))
        effects.extend(self._reward_magnitude_effect(ctx, candidate_mechanic, enemy_mechanic))
        effects.extend(self._extend_or_cut_effect(ctx, candidate_mechanic, enemy_mechanic))
        return effects

    @staticmethod
    def _accelerator_clause(owner, mechanic, accelerators: tuple[Ability, ...], premises: list[FactRef]) -> str:
        """Cita el/los efecto(s) acelerador(es) REALMENTE encontrados (no
        un tipo fijo por posición) y, si la misma habilidad también
        ralentiza, agrega la cláusula de "conservar contacto" — sin
        sumar un delta aparte: es la misma cadena causal."""

        if not accelerators:
            return ""
        ability = accelerators[0]
        matched_types = sorted(ability.effect_types() & _ACCELERATOR_TYPES, key=lambda t: t.value)
        for t in matched_types:
            premises.append(_fact(owner.id, ability.slot, t, "accelerator"))
        slows = ability.effects_of(EffectType.SLOW)
        if not slows:
            return f" {ability.name} de {owner.name} adelanta la siguiente aplicación válida hacia {mechanic.name}."
        premises.append(_fact(owner.id, ability.slot, EffectType.SLOW, "contact"))
        return (
            f" {ability.name} de {owner.name} adelanta la siguiente aplicación válida hacia {mechanic.name} "
            f"mediante el reset del ataque, y su ralentización ayuda a {owner.name} a conservar contacto para "
            "intentar completar las cargas posteriores."
        )

    def _structural_threshold_effect(self, ctx, candidate_mechanic, enemy_mechanic) -> list[RuleEffect]:
        candidate_accelerators = accelerator_abilities(ctx.candidate, candidate_mechanic, ctx.phase)
        enemy_accelerators = accelerator_abilities(ctx.enemy, enemy_mechanic, ctx.phase)
        candidate_rank = ramp_speed_rank(ctx.candidate, candidate_mechanic, ctx.phase)
        enemy_rank = ramp_speed_rank(ctx.enemy, enemy_mechanic, ctx.phase)
        if candidate_rank == enemy_rank and not candidate_accelerators and not enemy_accelerators:
            return []

        premises = [
            FactRef(f"{ctx.candidate.id}.stacking.{candidate_mechanic.id}.applications_needed", candidate_mechanic.applications_needed),
            FactRef(f"{ctx.enemy.id}.stacking.{enemy_mechanic.id}.applications_needed", enemy_mechanic.applications_needed),
        ]
        candidate_clause = self._accelerator_clause(ctx.candidate, candidate_mechanic, candidate_accelerators, premises)
        enemy_clause = self._accelerator_clause(ctx.enemy, enemy_mechanic, enemy_accelerators, premises)

        risk_clause = ""
        if (
            enemy_accelerators
            and candidate_mechanic.applications_needed < enemy_mechanic.applications_needed
        ):
            ability = enemy_accelerators[0]
            risk_clause = (
                f" Aunque {ctx.candidate.name} activa {candidate_mechanic.name} con menos impactos "
                f"({candidate_mechanic.applications_needed} vs {enemy_mechanic.applications_needed}), el reset y "
                f"la ralentización de {ability.name} de {ctx.enemy.name} facilitan que {ctx.enemy.name} mantenga "
                f"el intercambio y continúe acumulando {enemy_mechanic.name}."
            )

        text = (
            f"Estructuralmente, {candidate_mechanic.name} de {ctx.candidate.name} requiere "
            f"{candidate_mechanic.applications_needed} aplicaciones válidas desde {len(candidate_mechanic.applied_by)} "
            f"fuente(s), mientras que {enemy_mechanic.name} de {ctx.enemy.name} requiere "
            f"{enemy_mechanic.applications_needed} desde {len(enemy_mechanic.applied_by)} fuente(s). Esto es un "
            "orden estructural, no una predicción de quién activa primero: cadencia de golpes, cooldowns, acierto "
            f"y secuencia no se modelan en esta V0.{candidate_clause}{enemy_clause}{risk_clause}"
        )

        return [
            RuleEffect(
                factor=Factor.POWER_SPIKES,
                polarity=Polarity.CONDITIONAL,
                delta=0.05,
                text=text,
                premises=tuple(premises),
                condition="el umbral estructuralmente menor no garantiza activarse primero en el tiempo real de la partida",
                invalidated_if="cadencia de golpes, cooldowns, acierto y secuencia de habilidades no se modelan en esta V0",
                condition_kind=ConditionKind.STRATEGIC,
                category="stack_race",
            )
        ]

    def _reward_magnitude_effect(self, ctx, candidate_mechanic, enemy_mechanic) -> list[RuleEffect]:
        candidate_reward = reward_magnitude(ctx.candidate, candidate_mechanic, ctx.phase)
        enemy_reward = reward_magnitude(ctx.enemy, enemy_mechanic, ctx.phase)
        if candidate_reward == enemy_reward:
            return []
        polarity = Polarity.PRO if candidate_reward > enemy_reward else Polarity.CONTRA
        premises = [
            FactRef(f"{ctx.candidate.id}.stacking.{candidate_mechanic.id}.reward_magnitude@{ctx.phase.value}", candidate_reward),
            FactRef(f"{ctx.enemy.id}.stacking.{enemy_mechanic.id}.reward_magnitude@{ctx.phase.value}", enemy_reward),
        ]
        for eff in candidate_mechanic.reward_effects:
            premises.append(FactRef(f"{ctx.candidate.id}.stacking.{candidate_mechanic.id}.reward.{eff.type.value}", eff.magnitude))

        return [
            RuleEffect(
                factor=Factor.POWER_SPIKES,
                polarity=polarity,
                delta=0.06,
                text=(
                    f"Si el intercambio se extiende lo suficiente, la recompensa de {ctx.candidate.name} al "
                    f"alcanzar {candidate_mechanic.reward_name} (magnitud agregada {candidate_reward} en esta "
                    f"fase) {'supera' if polarity == Polarity.PRO else 'queda por debajo de'} la de "
                    f"{ctx.enemy.name} ({enemy_mechanic.reward_name}, magnitud {enemy_reward})."
                ),
                premises=tuple(premises),
                invalidated_if=(
                    "la magnitud agregada suma efectos ordinales de tipos heterogéneos (empoderamiento propio, "
                    "aura, velocidad); es una comparación cualitativa aproximada, no unidades equivalentes"
                ),
                category="stack_race",
            )
        ]

    def _extend_or_cut_effect(self, ctx, candidate_mechanic, enemy_mechanic) -> list[RuleEffect]:
        enemy_cut_tools = [a for a in ctx.enemy_abilities() if TacticalUse.TRADE_CUT in a.tactical_uses]
        condition = (
            "extender el intercambio acerca a ambos lados a su propia recompensa de acumulación; "
            "alcanzar el umbral rival primero castiga seguir peleando en vez de cortar"
        )
        if enemy_cut_tools:
            condition += f", y {ctx.enemy.name} puede intentar cortarlo antes con {enemy_cut_tools[0].name}"
        return [
            RuleEffect(
                factor=Factor.RELIABILITY,
                polarity=Polarity.CONDITIONAL,
                delta=0.08,
                text=(
                    f"La conclusión sobre este intercambio depende de si se extiende lo suficiente para que "
                    f"{candidate_mechanic.name} o {enemy_mechanic.name} lleguen a su recompensa, no es "
                    "automática desde el primer contacto."
                ),
                premises=(),
                condition=condition,
                invalidated_if=(
                    "el ritmo real de intercambio (auto-ataques efectivamente conectados por segundo) no se "
                    "simula en esta V0; el orden de acumulación es cualitativo"
                ),
                condition_kind=ConditionKind.STRATEGIC,
                category="stack_race",
            )
        ]


STACKING_RULES: tuple[Rule, ...] = (StackRaceRule(),)
