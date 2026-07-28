"""
Transform functions a device binding (ontology/bindings/) can reference by
name to reconcile a raw tag's representation with the profile's declared
unit and type. Deliberately small -- these exist to solve real, common PLC
integration mismatches (scaled integers, Fahrenheit, 0/1 flags, fractions),
not to be a general expression language.
"""


def identity(value):
    return value


def divide_10(value):
    return value / 10


def fahrenheit_to_celsius(value):
    return (value - 32) * 5 / 9


def int_to_bool(value):
    return bool(value)


def fraction_to_percent(value):
    return value * 100


TRANSFORMS = {
    "identity": identity,
    "divide_10": divide_10,
    "fahrenheit_to_celsius": fahrenheit_to_celsius,
    "int_to_bool": int_to_bool,
    "fraction_to_percent": fraction_to_percent,
}


def apply(transform_name: str, value):
    fn = TRANSFORMS.get(transform_name)
    if fn is None:
        raise ValueError(f"Unknown transform {transform_name!r}")
    return fn(value)
