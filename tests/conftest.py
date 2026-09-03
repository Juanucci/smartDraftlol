from __future__ import annotations

import pytest

from lol_reasoner.knowledge.loader import load_all_champions


@pytest.fixture(scope="session")
def champions():
    return load_all_champions()


@pytest.fixture(scope="session")
def darius(champions):
    return champions["darius"]


@pytest.fixture(scope="session")
def mordekaiser(champions):
    return champions["mordekaiser"]
