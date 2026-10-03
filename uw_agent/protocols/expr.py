"""Tiny safe expression language for protocol `when` / `applies_when` / requiredWhen / on_conflict.

Grammar:  or / and / not, comparisons (==, !=, >, >=, <, <=), `in (a, b)`, `not in`,
parentheses, literals (numbers, "strings", true, false), identifiers (field names).
Evaluation is three-valued (Kleene): a comparison involving a missing (None) field is UNKNOWN,
and `UNKNOWN and False == False`, `UNKNOWN or True == True`.  No eval(); no attribute access.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


class _Unknown:
    def __repr__(self) -> str:
        return "UNKNOWN"

    def __bool__(self) -> bool:  # guard against accidental truthiness
        raise TypeError("UNKNOWN has no truth value; compare with `is UNKNOWN`")


UNKNOWN = _Unknown()


class ExprError(ValueError):
    pass


_TOKEN = re.compile(r"""\s*(?:
    (?P<num>-?\d+(?:\.\d+)?)|
    (?P<str>"(?:[^"\\]|\\.)*")|
    (?P<op>==|!=|>=|<=|>|<|\(|\)|,)|
    (?P<id>[A-Za-z_][A-Za-z0-9_]*)
)""", re.X)
_KEYWORDS = {"and", "or", "not", "in", "true", "false"}


def _tokenize(src: str) -> list[tuple[str, Any]]:
    pos, out = 0, []
    src = src.strip()
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise ExprError(f"cannot tokenize {src[pos:pos + 20]!r} in {src!r}")
        pos = m.end()
        if m.group("num") is not None:
            t = m.group("num")
            out.append(("lit", float(t) if "." in t else int(t)))
        elif m.group("str") is not None:
            out.append(("lit", bytes(m.group("str")[1:-1], "utf-8").decode("unicode_escape")))
        elif m.group("op") is not None:
            out.append(("op", m.group("op")))
        else:
            w = m.group("id")
            if w in ("true", "false"):
                out.append(("lit", w == "true"))
            elif w in _KEYWORDS:
                out.append(("kw", w))
            else:
                out.append(("id", w))
    return out


@dataclass
class Expr:
    source: str
    ast: Any

    def fields(self) -> set[str]:
        acc: set[str] = set()
        _collect(self.ast, acc)
        return acc

    def literals(self) -> list[tuple[str, str, Any]]:
        """(field, op, literal) for each simple `field <op> literal` / `field in (...)` comparison."""
        acc: list[tuple[str, str, Any]] = []
        _collect_cmp(self.ast, acc)
        return acc

    def evaluate(self, values: dict[str, Any]) -> Any:
        """True / False / UNKNOWN."""
        return _eval(self.ast, values)

    def unknown_fields(self, values: dict[str, Any]) -> set[str]:
        """Identifiers referenced here whose value is missing."""
        return {f for f in self.fields() if values.get(f) is None}


class _Parser:
    def __init__(self, toks: list[tuple[str, Any]], src: str):
        self.t, self.i, self.src = toks, 0, src

    def peek(self) -> Optional[tuple[str, Any]]:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> tuple[str, Any]:
        tok = self.peek()
        if tok is None:
            raise ExprError(f"unexpected end of expression: {self.src!r}")
        self.i += 1
        return tok

    def is_kw(self, w: str) -> bool:
        p = self.peek()
        return p is not None and p == ("kw", w)

    def parse(self) -> Any:
        node = self.or_()
        if self.peek() is not None:
            raise ExprError(f"unexpected token {self.peek()!r} in {self.src!r}")
        return node

    def or_(self) -> Any:
        n = self.and_()
        while self.is_kw("or"):
            self.take()
            n = ("or", n, self.and_())
        return n

    def and_(self) -> Any:
        n = self.not_()
        while self.is_kw("and"):
            self.take()
            n = ("and", n, self.not_())
        return n

    def not_(self) -> Any:
        if self.is_kw("not"):
            self.take()
            return ("not", self.not_())
        return self.cmp()

    def atom(self) -> Any:
        k, v = self.take()
        if k == "lit":
            return ("lit", v)
        if k == "id":
            return ("id", v)
        if (k, v) == ("op", "("):
            n = self.or_()
            if self.take() != ("op", ")"):
                raise ExprError(f"missing ) in {self.src!r}")
            return n
        raise ExprError(f"unexpected {v!r} in {self.src!r}")

    def cmp(self) -> Any:
        left = self.atom()
        p = self.peek()
        if p and p[0] == "op" and p[1] in ("==", "!=", ">=", "<=", ">", "<"):
            self.take()
            return ("cmp", p[1], left, self.atom())
        negate = False
        if self.is_kw("not") and self.t[self.i + 1:self.i + 2] == [("kw", "in")]:
            self.take()
            negate = True
        if self.is_kw("in"):
            self.take()
            if self.take() != ("op", "("):
                raise ExprError(f"`in` needs ( ... ) in {self.src!r}")
            items = [self.atom()]
            while self.peek() == ("op", ","):
                self.take()
                items.append(self.atom())
            if self.take() != ("op", ")"):
                raise ExprError(f"missing ) in {self.src!r}")
            n = ("in", left, items)
            return ("not", n) if negate else n
        return left


def parse(src: str) -> Expr:
    return Expr(src, _Parser(_tokenize(src), src).parse())


def _collect(n: Any, acc: set[str]) -> None:
    if n[0] == "id":
        acc.add(n[1])
    elif n[0] in ("and", "or"):
        _collect(n[1], acc); _collect(n[2], acc)
    elif n[0] == "not":
        _collect(n[1], acc)
    elif n[0] == "cmp":
        _collect(n[2], acc); _collect(n[3], acc)
    elif n[0] == "in":
        _collect(n[1], acc)
        for it in n[2]:
            _collect(it, acc)


def _collect_cmp(n: Any, acc: list) -> None:
    if n[0] == "cmp" and n[2][0] == "id" and n[3][0] == "lit":
        acc.append((n[2][1], n[1], n[3][1]))
    elif n[0] == "in" and n[1][0] == "id":
        for it in n[2]:
            if it[0] == "lit":
                acc.append((n[1][1], "in", it[1]))
    elif n[0] in ("and", "or"):
        _collect_cmp(n[1], acc); _collect_cmp(n[2], acc)
    elif n[0] == "not":
        _collect_cmp(n[1], acc)


def _val(n: Any, values: dict[str, Any]) -> Any:
    if n[0] == "lit":
        return n[1]
    if n[0] == "id":
        v = values.get(n[1])
        return UNKNOWN if v is None else v
    raise ExprError("only literals/identifiers can be compared")


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if type(a) is not type(b) and isinstance(a, (int, float, str)) and isinstance(b, (int, float, str)):
        return str(a) == str(b)  # select options like "9" vs literal 9
    return a == b


def _eval(n: Any, values: dict[str, Any]) -> Any:
    k = n[0]
    if k == "lit":
        return n[1]
    if k == "id":
        return _val(n, values)
    if k == "not":
        v = _eval(n[1], values)
        return UNKNOWN if v is UNKNOWN else (not v)
    if k == "and":
        a, b = _eval(n[1], values), _eval(n[2], values)
        if a is False or b is False:
            return False
        return UNKNOWN if (a is UNKNOWN or b is UNKNOWN) else True
    if k == "or":
        a, b = _eval(n[1], values), _eval(n[2], values)
        if a is True or b is True:
            return True
        return UNKNOWN if (a is UNKNOWN or b is UNKNOWN) else False
    if k == "in":
        left = _val(n[1], values)
        if left is UNKNOWN:
            return UNKNOWN
        return any(_eq(left, _val(it, values)) for it in n[2])
    if k == "cmp":
        a, b = _val(n[2], values), _val(n[3], values)
        if a is UNKNOWN or b is UNKNOWN:
            return UNKNOWN
        op = n[1]
        if op == "==":
            return _eq(a, b)
        if op == "!=":
            return not _eq(a, b)
        try:
            return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]
        except TypeError:
            return UNKNOWN
    raise ExprError(f"bad node {n!r}")


def parse_required_when(text: str, field_names: set[str]) -> Expr:
    """Convert the registry's free-text `requiredWhen` into an Expr.

    `a = true`, `a != None`, `a = Above Ground`, `a in (Piers, Stilts)`, `a in (9, 10)`:
    single `=` becomes `==`; bare words that are not field names / and / or / true / false /
    numbers are quoted as string literals (multi-word values like `Above Ground` are joined).
    """
    s = re.sub(r"(?<![=!<>])=(?!=)", " == ", text.strip())
    toks = re.findall(r'==|!=|>=|<=|>|<|\(|\)|,|[^\s(),=!<>]+', s)
    out: list[str] = []
    i = 0
    prev_op = False  # previous token was a comparison operator or `(`/`,` inside an `in` list
    while i < len(toks):
        t = toks[i]
        if t in ("==", "!=", ">=", "<=", ">", "<", "(", ")", ","):
            out.append(t)
            prev_op = t not in (")",)
            i += 1
            continue
        low = t.lower()
        if low in ("and", "or", "not", "in") and not prev_op:
            out.append(low); prev_op = False; i += 1; continue
        if t in field_names and not prev_op:
            out.append(t); prev_op = False; i += 1; continue
        if low in ("true", "false") or re.fullmatch(r"-?\d+(\.\d+)?", t):
            out.append(low if low in ("true", "false") else t); prev_op = False; i += 1; continue
        words = [t]  # a bare string value, possibly multi-word, up to an operator
        i += 1
        while i < len(toks) and toks[i] not in ("==", "!=", ">=", "<=", ">", "<", "(", ")", ",") \
                and toks[i].lower() not in ("and", "or"):
            words.append(toks[i]); i += 1
        out.append('"' + " ".join(words) + '"')
        prev_op = False
    return parse(" ".join(out))
