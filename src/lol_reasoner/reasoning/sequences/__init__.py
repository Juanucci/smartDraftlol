"""Tipos de secuencia y resultado (v1.7, Etapa 2).

Solo tipos genéricos, inmutables y sus invariantes — sin secuencias
concretas, sin motor de transición, sin generador de escenarios, sin
scoring ni integración con `RuleEngine`/`ReasoningTrace`. Ver los
docstrings de `steps.py` y `sequence.py` para el alcance exacto de cada
tipo y `docs/design/v1.7-sequence-state-design.md` §B.3/B.6/B.8/B.9/B.11
para el contrato de diseño que estos tipos implementan.
"""

from __future__ import annotations

from lol_reasoner.reasoning.sequences.sequence import (
    AlternativeGroup,
    CausalComponent,
    Evaluation,
    InteractionSequence,
    ScenarioOutcome,
    StateDelta,
    StepResult,
    TerminalEvent,
    TerminalEventKind,
    TradeOutcome,
    chain_support,
)
from lol_reasoner.reasoning.sequences.steps import (
    ActorRole,
    EffectIdentity,
    PreconditionStatus,
    SequenceStep,
    resolve_step_support,
)

__all__ = [
    "ActorRole",
    "AlternativeGroup",
    "CausalComponent",
    "EffectIdentity",
    "Evaluation",
    "InteractionSequence",
    "PreconditionStatus",
    "ScenarioOutcome",
    "SequenceStep",
    "StateDelta",
    "StepResult",
    "TerminalEvent",
    "TerminalEventKind",
    "TradeOutcome",
    "chain_support",
    "resolve_step_support",
]
