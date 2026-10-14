"""End to end: chart -> code -> a real Python process -> the text on its terminal."""
import pytest

from flow2code.codegen import generate
from flow2code.runner import run


def run_chart(chart, name, stdin):
    fc = chart(name)
    res = run(generate(fc), stdin=stdin)
    assert res.ok, res.stderr
    return res.stdout


# The prompt strings are part of stdout, because that is what a terminal shows: the Read
# blocks turn into input("Enter n: "), so the text a student sees is exactly this.
@pytest.mark.parametrize("name,stdin,want", [
    ("even_odd", "7\n", "Enter n: Odd\n"),
    ("even_odd", "8\n", "Enter n: Even\n"),
    ("largest_of_two", "4\n9\n", "Enter a: Enter b: largest 9\n"),
    ("largest_of_two", "9\n4\n", "Enter a: Enter b: largest 9\n"),
    ("sum_loop", "5\n", "Enter n: sum is 15\n"),
    ("sum_loop", "1\n", "Enter n: sum is 1\n"),
    ("sum_loop", "0\n", "Enter n: sum is 0\n"),
    ("calculator", "8\n2\n*\n", 'Enter a: Enter b: Enter op: unknown\n'),
    ("calculator", "8\n2\n-\n", "Enter a: Enter b: Enter op: 6\n"),
    ("nested_if", "0\n", "Enter n: zero\n"),
    ("nested_if", "-3\n", "Enter n: negative\n"),
])
def test_samples_produce_the_expected_output(chart, name, stdin, want):
    assert run_chart(chart, name, stdin) == want


def test_a_loop_that_never_ends_is_reported_as_a_timeout(chart):
    """Loop guards are the number one student bug; the runner must not hang."""
    fc = chart("sum_loop")
    d = fc.to_dict()
    for node in d["nodes"]:
        if node["id"] == "l7":
            node["text"] = "i = i"           # forgot to update the counter
    from flow2code.models import Flowchart
    from flow2code.graph import build, validate
    from flow2code.codegen import generate as gen
    broken = Flowchart.from_dict(d)
    res = run(gen(broken, validate(broken, build(broken))), stdin="5\n", timeout=1.0)
    assert res.timed_out
    assert "ran out of time" in res.describe()


def test_generated_code_is_not_allowed_to_import(chart):
    """A block is copied verbatim only if it is a plain assignment: no imports, no eval."""
    from flow2code.graph import Flow2CodeError
    from flow2code.models import Flowchart
    d = chart("even_odd").to_dict()
    d["nodes"].insert(2, {"id": "n9", "type": "process", "text": "import os", "x": 0, "y": 0})
    d["edges"] = [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n9"}, {"from": "n9", "to": "n3"},
                  {"from": "n3", "to": "n4", "label": "yes"}, {"from": "n3", "to": "n5", "label": "no"},
                  {"from": "n4", "to": "n6"}, {"from": "n5", "to": "n6"}]
    fc = Flowchart.from_dict(d)
    with pytest.raises(Flow2CodeError, match="may not do"):
        generate(fc)
