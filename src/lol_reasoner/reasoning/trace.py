"""`ReasoningTrace`: el único lugar donde nace evidencia.

Regla de oro del proyecto: ninguna razón, riesgo, condición o delta de
score puede aparecer en la salida si no está respaldado por un
`TraceEntry`. El `Narrator` (explain/narrator.py) y el `Scorer`
(scoring/) solo *leen* la traza; no generan contenido propio.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lol_reasoner.domain.enums import (
    ConditionKind,
    Factor,
    Phase,
    Polarity,
    Provenance,
    Support,
    phase_index,
)


@dataclass(frozen=True, slots=True)
class FactRef:
    """Un hecho puntual usado como premisa de una regla.

    Ejemplo: FactRef("Darius.axes.early_pressure", 4)
    """

    path: str
    value: object


_SUPPORT_ORDER = {Support.STRUCTURAL: 2, Support.CONDITIONED: 1, Support.AMBIGUOUS: 0}


def _support_rank(support: Support) -> int:
    return _SUPPORT_ORDER[support]


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
    causal_key: str | None = None  # ver RuleEffect.causal_key
    condition_kind: ConditionKind | None = None  # ver RuleEffect.condition_kind
    support: Support = Support.STRUCTURAL  # ver RuleEffect.support
    provenance: Provenance = Provenance.DERIVED  # ver RuleEffect.provenance


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

    def deduped_for_scoring(self, subject_id: str) -> list[TraceEntry]:
        """Vista de las entradas de `subject_id` para cálculo de score y
        para las listas planas de razones/riesgos: cuando varias entradas
        comparten `causal_key` (misma fuente mecánica, citada por la
        misma o distinta regla, en la misma o distinta fase), se conserva
        solo la de mayor |delta| — empatada, la de fase más temprana.
        Entradas con `causal_key=None` nunca se deduplican (se conservan
        todas, comportamiento sin cambios).

        Esta es la **vista causal**: la usan el scoring, el narrador y el
        cálculo de contradicciones de Confidence, para que una sola causa
        mecánica no cuente varias veces por reaparecer en varias fases o
        por ser citada por dos reglas.

        La traza CRUDA (`entries`, `for_phase`) se conserva íntegra para
        auditoría, y `build_phase_notes` muestra las dos vistas por
        separado y etiquetadas: que un hecho siga vigente en level_6,
        first_item y side_lane_late es información real, pero no es una
        ventaja tres veces más grande.
        """

        own = [e for e in self.entries if e.subject == subject_id]
        keyed: dict[str, TraceEntry] = {}
        unkeyed: list[TraceEntry] = []
        for e in own:
            if e.causal_key is None:
                unkeyed.append(e)
                continue
            current = keyed.get(e.causal_key)
            if current is None:
                keyed[e.causal_key] = e
                continue
            # Desempate config-independiente: mayor |delta|, luego mayor
            # certeza (STRUCTURAL > CONDITIONED > AMBIGUOUS), luego fase
            # más temprana. No usa los pesos de config/weights.yaml para
            # que la vista causal no dependa de la calibración.
            current_rank = (abs(current.delta), _support_rank(current.support), -phase_index(current.phase))
            candidate_rank = (abs(e.delta), _support_rank(e.support), -phase_index(e.phase))
            if candidate_rank > current_rank:
                keyed[e.causal_key] = e
        return unkeyed + list(keyed.values())
