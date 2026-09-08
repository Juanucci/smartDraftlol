"""CLI de demostración.

Ejemplo:
    python -m lol_reasoner recommend --enemy Darius --candidates Mordekaiser \\
        --mastery Mordekaiser=80 --json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from lol_reasoner.domain.enums import ALL_PHASES, Phase
from lol_reasoner.domain.query import MatchupQuery
from lol_reasoner.domain.result import RecommendationSet
from lol_reasoner.knowledge.loader import load_all_champions
from lol_reasoner.recommend import recommend


def _build_name_index(champions: dict) -> dict[str, str]:
    """Mapa case-insensitive de id/nombre -> id, para aceptar '--enemy Darius' o 'darius'."""

    index: dict[str, str] = {}
    for cid, champ in champions.items():
        index[cid.lower()] = cid
        index[champ.name.lower()] = cid
    return index


def _resolve(name: str, index: dict[str, str]) -> str:
    key = name.strip().lower()
    if key not in index:
        raise SystemExit(f"Campeón desconocido: '{name}'. Disponibles: {sorted({v for v in index.values()})}")
    return index[key]


def _parse_mastery(raw: str | None, index: dict[str, str]) -> dict[str, int]:
    if not raw:
        return {}
    mastery: dict[str, int] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise SystemExit(f"--mastery mal formado en '{pair}', se espera Campeon=0..100")
        name, value = pair.split("=", 1)
        cid = _resolve(name, index)
        try:
            level = int(value)
        except ValueError as exc:
            raise SystemExit(f"--mastery: valor no numérico para {name}: '{value}'") from exc
        if not (0 <= level <= 100):
            raise SystemExit(f"--mastery: {name}={level} fuera de rango [0,100]")
        mastery[cid] = level
    return mastery


def _parse_phases(raw: str | None) -> tuple[Phase, ...] | None:
    if not raw:
        return None
    phases = []
    for name in raw.split(","):
        name = name.strip()
        if not name:
            continue
        try:
            phases.append(Phase(name))
        except ValueError as exc:
            valid = [p.value for p in Phase]
            raise SystemExit(f"Fase inválida '{name}'. Válidas: {valid}") from exc
    return tuple(phases) if phases else None


def _fmt_score(v: float) -> str:
    return f"{v:.1f}"


def format_human(rs: RecommendationSet) -> str:
    lines: list[str] = []
    lines.append(f"Matchup: candidatos vs {rs.enemy_name} (knowledge_version={rs.knowledge_version})")
    lines.append(
        "El MatchupScore es un índice heurístico SIN CALIBRAR de adecuación mecánica relativa (0-100) de esta "
        "V0: no es un winrate ni una probabilidad de victoria. La conclusión útil es la dirección, la "
        "intensidad y la estabilidad; el número es un dato técnico secundario."
    )
    lines.append("")
    if len(rs.ranking_global) > 1:
        lines.append(f"Ranking global:   {' > '.join(_label(rs, c, 'global') for c in rs.ranking_global)}")
        lines.append(f"Ranking personal: {' > '.join(_label(rs, c, 'personal') for c in rs.ranking_personal)}")
        lines.append(f"Mejor pick global:   {rs.recommendations[rs.best_global].candidate_name}")
        lines.append(f"Mejor pick personal: {rs.recommendations[rs.best_personal].candidate_name}")
    else:
        # Un solo candidato: no ganó ninguna comparación, así que no se
        # anuncia como "mejor pick" (v1.6.1).
        only = rs.recommendations[rs.ranking_global[0]]
        lines.append(f"Candidato evaluado: {only.candidate_name} (sin comparación: es el único candidato de la consulta)")
    lines.append("=" * 72)

    for cid in rs.ranking_global:
        rec = rs.recommendations[cid]
        lines.append("")
        lines.append(f"## {rec.candidate_name}  (candidate_id={rec.candidate_id})")
        mastery_txt = f"{rec.mastery}/100" if rec.mastery is not None else "sin dato (se asume neutral)"

        # Lo primero es la conclusión cualitativa; el número queda como
        # dato técnico secundario (es un índice heurístico sin calibrar,
        # no un winrate).
        lines.append(f"CONCLUSIÓN: {rec.lean.summary}")
        if rec.lean.main_factors:
            lines.append(f"  Factores principales: {', '.join(rec.lean.main_factors)}")
        lines.append(
            f"  Cobertura epistémica interna (cuánto miró el motor, NO certeza del veredicto): "
            f"{rec.confidence.candidate_knowledge_coverage_level.upper()} "
            f"({rec.confidence.candidate_knowledge_coverage_score})"
        )
        lines.append("")
        lines.append(
            f"  [dato técnico] MatchupScore mecánico: {_fmt_score(rec.global_score)}   "
            f"PersonalScore: {_fmt_score(rec.personal_score)}   Mastery: {mastery_txt}"
        )
        lines.append("  Desglose por factor (evidencia mecánica DERIVADA, deduplicada por causal_key):")
        for factor, value in rec.factor_breakdown.items():
            lines.append(f"    - {factor}: {value:+.3f}")
        if rec.personal_breakdown is not None:
            pb = rec.personal_breakdown
            lines.append(
                f"  Por qué el PersonalScore es ese: required_skill={pb.required_skill} "
                f"(condiciones EXECUTION distintas: {pb.execution_condition_count}), "
                f"mastery={pb.mastery}, gap={pb.gap:+.1f}, ajuste={pb.adjustment:+.1f}"
            )
        lines.append("  Señales de confianza (cuatro preguntas distintas, no fusionadas):")
        for exp in rec.confidence.explanation:
            lines.append(f"    - {exp}")

        if rec.reasons:
            lines.append("  Ventajas mecánicas derivadas del kit (evidencia: id de traza):")
            for r in rec.reasons:
                lines.append(f"    + {r.text}  [{r.entry_id}]")
        if rec.risks:
            lines.append("  Riesgos / debilidades derivados del kit:")
            for r in rec.risks:
                lines.append(f"    - {r.text}  [{r.entry_id}]")
        if rec.editorial_priors:
            lines.append("  Priors editoriales (valoraciones manuales del YAML — NO puntúan, no las derivó el motor):")
            for r in rec.editorial_priors:
                lines.append(f"    ~ {r.text}  [{r.entry_id}]")
        if rec.uncalibrated_observations:
            lines.append("  Observaciones estructurales sin calibrar (reales, pero sin impacto cuantificable aún):")
            for r in rec.uncalibrated_observations:
                lines.append(f"    · {r.text}  [{r.entry_id}]")
        if rec.conditions:
            lines.append("  Condiciones que podrían cambiar la recomendación:")
            for r in rec.conditions:
                lines.append(f"    ? {r.text}  [{r.entry_id}]")
        if rec.missing_info:
            lines.append("  Información faltante:")
            for r in rec.missing_info:
                lines.append(f"    · {r.text}  [{r.entry_id}]")

        lines.append("  Por fase (vista cruda vs. causas NUEVAS que la fase desbloquea):")
        for phase in ALL_PHASES:
            note = rec.phase_notes[phase.value]
            lines.append(f"    [{phase.value}] {note.summary}")
            if note.effective_contributions_by_factor:
                detail = ", ".join(
                    f"{factor}: {value:+.3f}" for factor, value in sorted(note.effective_contributions_by_factor.items())
                )
                lines.append(f"        causas nuevas que aportan -> {detail}")

        lines.append("")
        lines.append(f"  SÍNTESIS: {rec.lean.summary}")
        if rec.lean.conditions_against_favored and rec.lean.favored_name:
            lines.append(f"    Qué podría reducir la ventaja estimada de {rec.lean.favored_name}:")
            for cond in rec.lean.conditions_against_favored:
                lines.append(f"      - {cond}")
        if rec.lean.conditions_favoring_other and rec.lean.other_name:
            lines.append(f"    Qué podría mejorar la posición de {rec.lean.other_name}:")
            for cond in rec.lean.conditions_favoring_other:
                lines.append(f"      - {cond}")

    lines.append("")
    lines.append("=" * 72)
    lines.append(
        "Nota: el conocimiento mecánico cargado es una lectura cualitativa propia, no auditada contra un "
        "parche concreto de LoL. Ver README > Limitaciones."
    )
    lines.append(
        "Nota: los scores de las dos direcciones de un mismo matchup son antisimétricos respecto de 50 por el "
        "invariante de reciprocidad (toda causa compartida pesa igual con signo opuesto). Que sumen 100 NO los "
        "convierte en probabilidades complementarias ni en un margen de victoria."
    )
    return "\n".join(lines)


def _label(rs: RecommendationSet, cid: str, which: str) -> str:
    rec = rs.recommendations[cid]
    score = rec.global_score if which == "global" else rec.personal_score
    return f"{rec.candidate_name}({_fmt_score(score)})"


def _to_json(rs: RecommendationSet) -> str:
    return json.dumps(dataclasses.asdict(rs), ensure_ascii=False, indent=2)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m lol_reasoner", description="Motor de razonamiento de matchups de top lane (V0).")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("recommend", help="Recomienda candidatos contra un enemigo dado.")
    rec.add_argument("--enemy", required=True, help="Campeón enemigo (id o nombre), p.ej. Darius")
    rec.add_argument("--candidates", default=None, help="Lista separada por comas. Si se omite, se usan todos los demás campeones cargados.")
    rec.add_argument("--mastery", default=None, help="Lista Campeon=0..100 separada por comas, p.ej. Mordekaiser=80,Garen=60")
    rec.add_argument("--phases", default=None, help=f"Lista separada por comas de {[p.value for p in Phase]}. Si se omite, se usan todas.")
    rec.add_argument("--champions-dir", default=None, type=Path, help="Directorio alternativo de YAML de campeones (por defecto, la KB embebida).")
    rec.add_argument("--json", action="store_true", help="Imprime el RecommendationSet completo como JSON en vez de texto legible.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "recommend":
        champions = load_all_champions(args.champions_dir)
        if len(champions) < 2:
            print(f"Se necesitan al menos 2 campeones cargados; hay {len(champions)}.", file=sys.stderr)
            return 1
        index = _build_name_index(champions)

        enemy_id = _resolve(args.enemy, index)
        candidate_ids = None
        if args.candidates:
            candidate_ids = tuple(_resolve(c, index) for c in args.candidates.split(",") if c.strip())
        mastery = _parse_mastery(args.mastery, index)
        phases = _parse_phases(args.phases)

        query = MatchupQuery(enemy_id=enemy_id, candidate_ids=candidate_ids, mastery=mastery, phases=phases)
        result_set = recommend(query, champions)

        if args.json:
            print(_to_json(result_set))
        else:
            print(format_human(result_set))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
