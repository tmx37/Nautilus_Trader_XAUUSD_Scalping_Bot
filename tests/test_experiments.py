"""Registro esperimenti, prereg e schemi (R2, R3): validità e regola append-only."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "experiments" / "schema"


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize("name", ["registry.schema.json", "prereg.schema.json", "report.schema.json"])
def test_schemas_are_valid(name):
    _validator(name)


def test_every_registry_line_matches_schema():
    validator = _validator("registry.schema.json")
    lines = (ROOT / "experiments" / "registry.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines, "il registro contiene almeno EXP-0000"
    for n, line in enumerate(lines, start=1):
        errors = sorted(validator.iter_errors(json.loads(line)), key=str)
        assert not errors, f"riga {n}: {[e.message for e in errors]}"


def test_prereg_template_matches_schema():
    data = yaml.safe_load((ROOT / "experiments" / "prereg" / "TEMPLATE.yaml").read_text(encoding="utf-8"))
    errors = sorted(_validator("prereg.schema.json").iter_errors(data), key=str)
    assert not errors, [e.message for e in errors]


def _checker():
    spec = importlib.util.spec_from_file_location(
        "check_registry", ROOT / "tools" / "check_registry_append_only.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("old", "new", "ok"),
    [
        ("", "a\n", True),
        ("a\n", "a\n", True),
        ("a\n", "a\nb\n", True),
        ("a\nb\n", "a\n", False),  # riga cancellata
        ("a\nb\n", "a\nc\n", False),  # riga modificata
        ("a\nb\n", "b\na\nb\n", False),  # riga inserita in testa
        ("a", "a\nb\n", False),  # ultima riga senza a capo estesa
    ],
)
def test_append_only_rule(old, new, ok):
    assert _checker().is_append_only(old, new) is ok
