"""D5: the generator stores archetype-consistent ground truth in the answer key."""

from pathlib import Path

import yaml

from leadgen import generator
from shared import registry

CONFIG = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "sim-harness/leadgen/generator_config.yaml").read_text()
)


def _queue(seed=42, difficulty="mixed"):
    return generator.generate_queue(seed, 10, difficulty, CONFIG)


def test_clean_fields_present_and_valid():
    for lead in _queue():
        clean = lead["debug"]["clean_fields"]
        assert registry.validate_lead_fields(clean) == []
        assert set(clean) == set(lead["fields"])


def test_required_fields_have_truth_when_nulled():
    for seed in (1, 42, 7):
        for lead in _queue(seed, "hard"):
            clean = lead["debug"]["clean_fields"]
            for name, value in lead["fields"].items():
                if value is None and registry.required_level(name) == "always":
                    assert clean[name] is not None, (lead["lead_id"], name)


def test_truth_never_leaks_into_perturbation_records():
    for lead in _queue(42, "hard"):
        for p in lead["debug"]["perturbations"]:
            assert "truth" not in p


def test_seed_reproducible():
    a = [l["fields"] for l in _queue()]
    b = [l["fields"] for l in _queue()]
    assert a == b
