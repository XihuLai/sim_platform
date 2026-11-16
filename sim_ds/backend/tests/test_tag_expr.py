import pytest
from backend.scenario.tag_expr import build_tag_sql, parse_tag_expr
from backend.shared.errors import AppError


def test_parse_and_build_expression() -> None:
    node = parse_tag_expr("A&B|C")
    assert node.op == "or"
    assert node.left is not None and node.left.op == "and"
    assert node.right is not None and node.right.tag == "C"
    params: dict[str, object] = {}
    sql = build_tag_sql(node, params)
    assert " OR " in sql
    assert params == {"tag_expr_0": "A", "tag_expr_1": "B", "tag_expr_2": "C"}


def test_parentheses_and_precedence() -> None:
    node = parse_tag_expr("(A|B)&C")
    assert node.op == "and"
    assert node.left is not None and node.left.op == "or"
    params: dict[str, object] = {}
    sql = build_tag_sql(node, params)
    assert " OR " in sql and ") AND EXISTS" in sql
    assert len(params) == 3


@pytest.mark.parametrize("expression", ["", "A&", "A|", "(A&B", "A&&B", "A)"])
def test_invalid_expression(expression: str) -> None:
    with pytest.raises(AppError) as exc:
        parse_tag_expr(expression)
    assert exc.value.code == "INVALID_TAG_EXPR"
