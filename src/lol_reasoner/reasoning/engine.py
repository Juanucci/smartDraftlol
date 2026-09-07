"""`RuleEngine`: recorre reglas y arma la `ReasoningTrace`.

Es el único lugar que traduce `RuleEffect` (lo que devuelve una regla)
en `TraceEntry` (lo que queda registrado). Ninguna regla escribe en la
traza directamente.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from lol_reasoner.domain.champion import Champion
from lol_reasoner.domain.enums import Factor, Phase, Polarity
from lol_reasoner.reasoning.context import ReasoningContext
from lol_reasoner.reasoning.rules.base import Rule, RuleEffect
from lol_reasoner.reasoning.rules.registry import ALL_GENERAL_RULES
from lol_reasoner.reasoning.rules.specific import SPECIFIC_INTERACTIONS, SpecificInteraction
from lol_reasoner.reasoning.trace import ReasoningTrace, TraceEntry

# Nota de alcance (declarada, no oculta): esta V0 no modela objetos
# concretos. Cada vez que se evalúa la fase FIRST_ITEM se dispara este
# aviso fijo de información faltante, para que la confianza lo refleje
# y la explicación lo muestre explícitamente en vez de fingir precisión.
_ITEM_GAP_RULE_ID = "ITEMGAP"
_ITEM_GAP_SUMMARY = (
    "Esta V0 no modela objetos concretos ni su timing: FIRST_ITEM es solo una fase "
    "aproximada de progresión de poder."
)


class RuleEngine:
    def __init__(
        self,
        general_rules: Sequence[Rule] = ALL_GENERAL_RULES,
        specific_interactions: Sequence[SpecificInteraction] = SPECIFIC_INTERACTIONS,
    ) -> None:
        self._general_rules = tuple(general_rules)
        self._specific_interactions = tuple(specific_interactions)

    def build_trace(self, candidate: Champion, enemy: Champion, phases: Sequence[Phase]) -> ReasoningTrace:
        trace = ReasoningTrace(candidate_id=candidate.id, enemy_id=enemy.id)
        seq: Counter[tuple[str, Phase]] = Counter()

        for phase in phases:
            ctx = ReasoningContext(candidate=candidate, enemy=enemy, phase=phase)

            for rule in self._general_rules:
                if not rule.applies_to_phase(phase):
                    continue
                for effect in rule.evaluate(ctx):
                    self._append(trace, seq, candidate.id, rule.id, rule.summary, rule.category, phase, effect)

            for interaction in self._specific_interactions:
                for effect in interaction.evaluate(ctx):
                    self._append(
                        trace,
                        seq,
                        candidate.id,
                        interaction.id,
                        interaction.justification,
                        interaction.category,
                        phase,
                        effect,
                    )

            if phase == Phase.FIRST_ITEM:
                self._append(
                    trace,
                    seq,
                    candidate.id,
                    _ITEM_GAP_RULE_ID,
                    _ITEM_GAP_SUMMARY,
                    "missing_item_data",
                    phase,
                    RuleEffect(
                        factor=Factor.RELIABILITY,
                        polarity=Polarity.CONDITIONAL,
                        delta=0.0,
                        text=(
                            f"No se conoce qué objeto concreto tendría {candidate.name} en esta fase de "
                            "progresión; una conclusión que dependa del objeto específico no está cubierta "
                            "por esta V0."
                        ),
                        condition="depende del objeto concreto comprado, fuera de alcance de esta V0",
                        invalidated_if="objetos y su timing no se modelan en esta V0",
                        category="missing_item_data",
                    ),
                )

        return trace

    @staticmethod
    def _append(
        trace: ReasoningTrace,
        seq: Counter[tuple[str, Phase]],
        subject_id: str,
        rule_id: str,
        rule_summary: str,
        default_category: str,
        phase: Phase,
        effect: RuleEffect,
    ) -> None:
        key = (rule_id, phase)
        n = seq[key]
        seq[key] += 1
        entry_id = f"{rule_id}#{phase.value}" if n == 0 else f"{rule_id}#{phase.value}#{n}"
        trace.add(
            TraceEntry(
                id=entry_id,
                rule_id=rule_id,
                rule_summary=rule_summary,
                category=effect.category or default_category,
                phase=phase,
                factor=effect.factor,
                polarity=effect.polarity,
                delta=effect.delta,
                premises=effect.premises,
                subject=subject_id,
                text=effect.text,
                condition=effect.condition,
                invalidated_if=effect.invalidated_if,
                causal_key=effect.causal_key,
                condition_kind=effect.condition_kind,
            )
        )
