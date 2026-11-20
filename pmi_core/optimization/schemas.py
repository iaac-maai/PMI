"""Normalized controlled input primitives."""
from pmi_core.scheduling.calendar import SchedulingError

def require(condition, message, code="MODEL_INVALID", **details):
    if not condition:
        raise SchedulingError(code, message, **details)


def supported(data, allowed):
    extra = data.keys() - allowed
    require(not extra, f"Unsupported fields: {sorted(extra)}.", "UNSUPPORTED_CONSTRAINT")


def integer(value, minimum=0):
    return type(value) is int and minimum <= value < 2**31
