"""Tag expression parser and SQL predicate builder.

Grammar (AND binds tighter than OR):

    expr    := term ("|" term)*
    term    := factor ("&" factor)*
    factor  := TAG | "(" expr ")"

Examples: ``A&B``, ``A&B|C``, ``(A|B)&C``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.shared.errors import AppError

_OPERATORS = {"&", "|", "(", ")"}


@dataclass(frozen=True)
class TagNode:
    op: str
    tag: str = ""
    left: TagNode | None = None
    right: TagNode | None = None


def _invalid(message: str) -> AppError:
    return AppError("INVALID_TAG_EXPR", "标签表达式无效", status=422, detail={"reason": message})


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    buffer: list[str] = []
    for char in text:
        if char in _OPERATORS:
            if buffer:
                token = "".join(buffer).strip()
                if token:
                    tokens.append(token)
                buffer = []
            tokens.append(char)
        else:
            buffer.append(char)
    if buffer:
        token = "".join(buffer).strip()
        if token:
            tokens.append(token)
    return tokens


class _Parser:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> str:
        token = self.peek()
        if token is None:
            raise _invalid("表达式提前结束")
        self.pos += 1
        return token

    def parse(self) -> TagNode:
        if not self.tokens:
            raise _invalid("表达式为空")
        node = self.expr()
        if self.peek() is not None:
            raise _invalid(f"无法解析的标记 {self.peek()}")
        return node

    def expr(self) -> TagNode:
        left = self.term()
        while self.peek() == "|":
            self.take()
            left = TagNode("or", left=left, right=self.term())
        return left

    def term(self) -> TagNode:
        left = self.factor()
        while self.peek() == "&":
            self.take()
            left = TagNode("and", left=left, right=self.factor())
        return left

    def factor(self) -> TagNode:
        token = self.take()
        if token == "(":
            node = self.expr()
            if self.take() != ")":
                raise _invalid("缺少右括号")
            return node
        if token in _OPERATORS:
            raise _invalid(f"意外的标记 {token}")
        return TagNode("tag", tag=token)


def parse_tag_expr(text: str) -> TagNode:
    return _Parser(_tokenize(text)).parse()


def build_tag_sql(node: TagNode, params: dict[str, Any]) -> str:
    counter = [0]
    return _build_node(node, params, counter)


def _build_node(node: TagNode, params: dict[str, Any], counter: list[int]) -> str:
    if node.op == "tag":
        index = counter[0]
        counter[0] += 1
        key = f"tag_expr_{index}"
        params[key] = node.tag
        return (
            f"EXISTS (SELECT 1 FROM scenario_tag st{index} JOIN tag t{index} "
            f"ON t{index}.id=st{index}.tag_id WHERE st{index}.scenario_id=s.id "
            f"AND t{index}.name=:{key})"
        )
    if node.left is None or node.right is None:
        raise _invalid("表达式节点不完整")
    left = _build_node(node.left, params, counter)
    right = _build_node(node.right, params, counter)
    return f"({left} {node.op.upper()} {right})"
