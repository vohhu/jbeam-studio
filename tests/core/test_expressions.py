import math
import random

import pytest

from jbeam_studio.core.assembly.expressions import Evaluator, ExpressionError, evaluate

VARIABLES = {
    "$a": 2,
    "$5wheel": 5,
    "$b": {"val": 3, "name": "$b"},
    "$components": {"val": {"engine": {"bore": 0.1, "type": "v8"}, "list": [10, 20]}},
}


@pytest.mark.parametrize("expression, expected", [
    ("$=1+2*3", 7),
    ("$=(1+2)*3", 9),
    ("$=-2^2", -4),
    ("$=2^3^2", 512),
    ("$=7 % 3", 1),
    ("$=-7 % 3", 2),
    ("$=10/4", 2.5),
    ("$=$a*$b", 6),
    ("$=$5wheel*2", 10),
    ("$=$tirepressure", None),
    ("$=$a == 2 and 'yes' or 'no'", "yes"),
    ("$=$missing == nil", True),
    ("$=not $missing", True),
    ("$='a'..1", "a1"),
    ("$=1 .. 2", "12"),
    ("$='x'..1.5", "x1.5"),
    ("$=$components.engine.bore * 10", 1.0),
    ("$=$components.engine.type ~= 'v8'", False),
    ("$=$components.gearbox == nil", True),
    ("$=$components.list[2]", 20),
    ("$=round(2.5)", 3),
    ("$=clamp(5, 0, 3)", 3),
    ("$=case(2, 'x', 'y', 'z')", "y"),
    ("$=case(false, 'x', 'y')", "y"),
    ("$=case(true, 'x', 'y')", "x"),
    ("$=case(9, 'x', 'y')", "y"),
    ("$=sqrt(16)", 4.0),
    ("$=max(1, 5, 3)", 5),
    ("$=floor(2.7)", 2),
    ("$=pi > 3", True),
    ("$=1/0", math.inf),
    ("$=smoothstep(0.5)", 0.5),
    ("$='1' + 2", 3),
    ("$=1 == true", False),
    ("$= 0x10 + 1", 17),
])
def test_evaluate(expression, expected):
    assert evaluate(expression, VARIABLES) == expected


@pytest.mark.parametrize("expression", [
    "$=$components.gearbox.ratio",
    "$=x = 1",
    "$=1 +",
    "$=include('a.csv')",
    "$='a' < 1",
    "$=nil .. 'a'",
    "$={1, 2}",
    "$=$a:foo()",
    "$=nosuchfunction(1)",
    "$=$a + 'x'",
])
def test_errors(expression):
    with pytest.raises(ExpressionError):
        evaluate(expression, VARIABLES)


def test_random_is_reproducible():
    first = Evaluator(random.Random(0)).evaluate("$=random(1, 1000)", {})
    second = Evaluator(random.Random(0)).evaluate("$=random(1, 1000)", {})
    assert first == second


def test_evaluate_safe_reports_errors():
    errors = []
    assert Evaluator().evaluate_safe("$=1 +", {}, errors.append) is None
    assert errors and errors[0].startswith('cannot evaluate "$=1 +"')
