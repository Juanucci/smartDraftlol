"""Carga de `config/weights.yaml` a un objeto tipado e inmutable."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

from lol_reasoner.domain.enums import Factor, Phase, Provenance, Support


@dataclass(frozen=True, slots=True)
class PersonalWeights:
    execution_sensitivity: float
    base_required_skill: float
    execution_demand_weight: float
    reliability_penalty_weight: float


@dataclass(frozen=True, slots=True)
class Weights:
    factor_weights: dict[Factor, float]
    phase_weights: dict[Phase, float]
    support_weights: dict[Support, float]
    provenance_weights: dict[Provenance, float]
    global_scale: float
    personal: PersonalWeights


def load_weights(path: Path | None = None) -> Weights:
    if path is None:
        with resources.files("lol_reasoner.config").joinpath("weights.yaml").open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    else:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

    return Weights(
        factor_weights={Factor(k): v for k, v in data["factors"].items()},
        phase_weights={Phase(k): v for k, v in data["phases"].items()},
        support_weights={Support(k): v for k, v in data["support"].items()},
        provenance_weights={Provenance(k): v for k, v in data["provenance"].items()},
        global_scale=data["global_scale"],
        personal=PersonalWeights(**data["personal"]),
    )


DEFAULT_WEIGHTS = load_weights()
