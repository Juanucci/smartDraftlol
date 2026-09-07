"""Narrator: convierte una `ReasoningTrace` en texto, sin inventar nada.

Regla dura: cada `ReasonItem` que produce este módulo lleva el `id` del
`TraceEntry` del que salió. No hay generación de texto libre desconectada
del cálculo — es lo que hace verificable (tests/test_trace_integrity.py)
que "la explicación coincide con los factores que realmente modificaron
el score".
"""

from __future__ import annotations

from collections import defaultdict

from lol_reasoner.domain.enums import ALL_PHASES, Phase, Polarity
from lol_reasoner.domain.result import PhaseNote, ReasonItem
from lol_reasoner.reasoning.trace import ReasoningTrace

_MAX_ITEMS = 8


def _dedup_by_text_strongest(entries: list) -> list:
    """Colapsa entradas con el mismo texto (típico de una interacción de kit que
    es constante a través de varias fases) quedándose con la de mayor delta.
    El id resultante sigue siendo una entrada real de la traza con ese texto."""

    best_by_text: dict[str, object] = {}
    for e in entries:
        current = best_by_text.get(e.text)
        if current is None or e.delta > current.delta:
            best_by_text[e.text] = e
    return sorted(best_by_text.values(), key=lambda e: e.delta, reverse=True)


def build_reasons(trace: ReasoningTrace, *, subject_id: str) -> tuple[ReasonItem, ...]:
    """Deduplica primero por `causal_key` (misma fuente mecánica citada
    por distintas reglas o en distintas fases: ver
    `ReasoningTrace.deduped_for_scoring`) y luego por texto — para que el
    usuario no lea "dos razones" que en realidad son un solo hecho."""

    deduped = [e for e in trace.deduped_for_scoring(subject_id) if e.polarity == Polarity.PRO]
    entries = _dedup_by_text_strongest(deduped)
    return tuple(ReasonItem(text=e.text, entry_id=e.id) for e in entries[:_MAX_ITEMS])


def build_risks(trace: ReasoningTrace, *, subject_id: str) -> tuple[ReasonItem, ...]:
    deduped = [e for e in trace.deduped_for_scoring(subject_id) if e.polarity == Polarity.CONTRA]
    entries = _dedup_by_text_strongest(deduped)
    return tuple(ReasonItem(text=e.text, entry_id=e.id) for e in entries[:_MAX_ITEMS])


def build_conditions(trace: ReasoningTrace) -> tuple[ReasonItem, ...]:
    """Toda entrada con `condition` no vacío, sin importar su polaridad.

    Una condición puede acompañar tanto a una ventaja (PRO) como a un
    riesgo (CONTRA) o a un efecto puramente condicional: lo que importa
    acá es que exprese bajo qué circunstancia se sostiene o se invierte.
    """

    entries = [e for e in trace.entries if e.condition]
    seen: set[str] = set()
    items: list[ReasonItem] = []
    for e in entries:
        if e.condition in seen:
            continue
        seen.add(e.condition)
        items.append(ReasonItem(text=e.condition, entry_id=e.id))
    return tuple(items[:_MAX_ITEMS])


def build_missing_info(trace: ReasoningTrace) -> tuple[ReasonItem, ...]:
    entries = [e for e in trace.entries if e.invalidated_if]
    seen: set[str] = set()
    items: list[ReasonItem] = []
    for e in entries:
        if e.invalidated_if in seen:
            continue
        seen.add(e.invalidated_if)
        items.append(ReasonItem(text=e.invalidated_if, entry_id=e.id))
    return tuple(items)


def build_phase_notes(trace: ReasoningTrace) -> dict[str, PhaseNote]:
    notes: dict[str, PhaseNote] = {}
    for phase in ALL_PHASES:
        entries = trace.for_phase(phase)
        net: dict[str, float] = defaultdict(float)
        sign = {Polarity.PRO: 1.0, Polarity.CONTRA: -1.0, Polarity.CONDITIONAL: 0.0}
        for e in entries:
            net[e.factor.value] += sign[e.polarity] * e.delta

        n_pro = sum(1 for e in entries if e.polarity == Polarity.PRO)
        n_contra = sum(1 for e in entries if e.polarity == Polarity.CONTRA)
        n_cond = sum(1 for e in entries if e.polarity == Polarity.CONDITIONAL)

        if not entries:
            summary = "Sin factores mecánicos registrados en esta fase para este candidato."
        else:
            parts = []
            if n_pro:
                parts.append(f"{n_pro} a favor")
            if n_contra:
                parts.append(f"{n_contra} en contra")
            if n_cond:
                parts.append(f"{n_cond} condicional(es)")
            summary = "Factores registrados en esta fase: " + ", ".join(parts) + "."

        notes[phase.value] = PhaseNote(
            phase=phase.value,
            net_delta_by_factor=dict(net),
            summary=summary,
            entry_ids=tuple(e.id for e in entries),
        )
    return notes
