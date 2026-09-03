"""`ReasoningTrace`: el único lugar donde nace evidencia.

Regla de oro del proyecto: ninguna razón, riesgo, condición o delta de
score puede aparecer en la salida si no está respaldado por un
`TraceEntry`. El `Narrator` (explain/narrator.py) y el `Scorer`
(scoring/) solo *leen* la traza; no generan contenido propio.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lol_reasoner.domain.enums import Factor, Phase, Polarity


@dataclass(frozen=True, slots=True)
class FactRef:
    """Un hecho puntual usado como premisa de una regla.

    Ejemplo: FactRef("Darius.axes.early_pressure", 4)
    """

    path: str
    value: object


@dataclass(frozen=True, slots=True)
class TraceEntry:
    id: str  # p.ej. "R003#early_lane"
    rule_id: str
    rule_summary: str
    category: str  # categoría mecánica, usada para cobertura de confianza
    phase: Phase
    factor: Factor
    polarity: Polarity
    delta: float  # aporte crudo (sin ponderar) al factor, en la fase indicada
    premises: tuple[FactRef, ...]
    subject: str  # candidate_id al que aplica el efecto (siempre el "pick" evaluado)
    text: str  # descripción legible, ya construida a partir de las premisas
    condition: str | None = None  # bajo qué circunstancia se sostiene / se invierte
    invalidated_if: str | None = None  # qué información faltante podría cambiarlo


@dataclass(slots=True)
class ReasoningTrace:
    """Log append-only de una evaluación candidato-vs-enemigo."""

    candidate_id: str
    enemy_id: str
    entries: list[TraceEntry] = field(default_factory=list)

    def add(self, entry: TraceEntry) -> None:
        self.entries.append(entry)

    def for_phase(self, phase: Phase) -> list[TraceEntry]:
        return [e for e in self.entries if e.phase == phase]

    def for_factor(self, factor: Factor) -> list[TraceEntry]:
        return [e for e in self.entries if e.factor == factor]

    def for_polarity(self, polarity: Polarity) -> list[TraceEntry]:
        return [e for e in self.entries if e.polarity == polarity]

    def categories(self) -> set[str]:
        return {e.category for e in self.entries}

    def get(self, entry_id: str) -> TraceEntry | None:
        return next((e for e in self.entries if e.id == entry_id), None)
