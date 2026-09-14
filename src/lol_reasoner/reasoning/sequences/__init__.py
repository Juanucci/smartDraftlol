"""Tipos de secuencia y resultado (v1.7, Etapa 2 — endurecida).

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
    ExecutionStatus,
    InteractionSequence,
    PreconditionResult,
    ScenarioOutcome,
    SequenceProgress,
    StateDelta,
    StepResult,
    TerminalEvent,
    TerminalEventKind,
    TradeOutcome,
    chain_execution_status,
    chain_support,
    execution_status_of,
    require_sequence_progress,
    scenario_outcome_to_primitive,
    sequence_progress,
    sequence_to_primitive,
)
from lol_reasoner.reasoning.sequences.steps import (
    WHOLE_EFFECT_COMPONENT,
    ActorRole,
    EffectIdentity,
    PostconditionEffectKind,
    PreconditionCheckKind,
    PreconditionStatus,
    SequenceStep,
    StructuralPostcondition,
    StructuralPrecondition,
    resolve_step_support,
)

__all__ = [
    "WHOLE_EFFECT_COMPONENT",
    "ActorRole",
    "AlternativeGroup",
    "CausalComponent",
    "EffectIdentity",
    "Evaluation",
    "ExecutionStatus",
    "InteractionSequence",
    "PostconditionEffectKind",
    "PreconditionCheckKind",
    "PreconditionResult",
    "PreconditionStatus",
    "ScenarioOutcome",
    "SequenceProgress",
    "SequenceStep",
    "StateDelta",
    "StepResult",
    "StructuralPostcondition",
    "StructuralPrecondition",
    "TerminalEvent",
    "TerminalEventKind",
    "TradeOutcome",
    "chain_execution_status",
    "chain_support",
    "execution_status_of",
    "require_sequence_progress",
    "resolve_step_support",
    "scenario_outcome_to_primitive",
    "sequence_progress",
    "sequence_to_primitive",
]
