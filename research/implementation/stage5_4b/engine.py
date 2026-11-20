"""Compatibility interface for the controlled research CLI and oracle scripts."""
from pmi_core.optimization import engine as _engine
from pmi_core.optimization.schemas import integer, require, supported
from .controlled_metadata import registry

cp_model = _engine.cp_model


def solve(problem, **kwargs):
    return _engine.solve(problem, registry=registry(), **kwargs)


def validate(problem, result):
    return _engine.validate(problem, result, registry=registry())


def prepare(problem, **kwargs):
    return _engine.prepare(problem, registry=registry(), **kwargs)
