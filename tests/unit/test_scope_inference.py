"""Unit tests for legacy-file scope inference (word-boundary keyword matching).

Regression coverage for the false-positive bug documented in
reporte-indexacion.md: substring matching on "go" misclassified any word
containing that substring (e.g. Spanish "código", "cargo") into the
`global-go` scope.
"""

from meridian.tools.knowledge_management import _infer_scope_from_text


def test_codigo_does_not_match_go():
    scope, suggested = _infer_scope_from_text(
        "esta regla habla de buen código limpio", "global"
    )
    assert scope == "global"
    assert suggested is True


def test_cargo_does_not_match_go():
    scope, suggested = _infer_scope_from_text(
        "revisar el cargo del responsable", "global"
    )
    assert scope == "global"
    assert suggested is True


def test_embargo_does_not_match_go():
    scope, suggested = _infer_scope_from_text("sin embargo, aplica la regla", "global")
    assert scope == "global"
    assert suggested is True


def test_javascript_does_not_match_java():
    scope, suggested = _infer_scope_from_text("usa javascript moderno", "global")
    assert scope == "global"
    assert suggested is True


def test_standalone_go_matches_global_go():
    scope, suggested = _infer_scope_from_text("reglas de estilo para go", "global")
    assert scope == "global-go"
    assert suggested is False


def test_standalone_java_matches_global_java():
    scope, suggested = _infer_scope_from_text("convenciones de java", "global")
    assert scope == "global-java"
    assert suggested is False


def test_go_fiber_matches_specific_scope_before_generic_go():
    scope, suggested = _infer_scope_from_text("usa go-fiber para el router", "global")
    assert scope == "global-go-fiber"
    assert suggested is False


def test_go_gin_matches_specific_scope_before_generic_go():
    scope, suggested = _infer_scope_from_text("usa go-gin para el router", "global")
    assert scope == "global-go-gin"
    assert suggested is False


def test_no_keyword_falls_back_to_default_scope():
    scope, suggested = _infer_scope_from_text(
        "regla general sin lenguaje especifico", "global-python"
    )
    assert scope == "global-python"
    assert suggested is True
