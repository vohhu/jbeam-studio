from jbeam_studio.core.diagnostics import DiagnosticList, Severity


class _Where:
    file = "a.jbeam"
    line = 3
    column = 7


def test_add_and_filter():
    diags = DiagnosticList()
    diags.add("error", "parse", "broken")
    diags.add(Severity.WARNING, "table", "odd")
    assert diags.has_errors()
    assert [d.message for d in diags.errors()] == ["broken"]
    assert [d.message for d in diags.warnings()] == ["odd"]


def test_at_uses_location():
    d = DiagnosticList().at(_Where(), "warning", "slots", "missing part")
    assert (d.file, d.line, d.column) == ("a.jbeam", 3, 7)
    assert str(d) == "a.jbeam:3:7: warning [slots] missing part"


def test_at_without_location():
    assert str(DiagnosticList().at(None, "info", "checks", "note")) == "info [checks] note"
