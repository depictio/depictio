"""Constant-fold the context a code-mode figure is executed with (RFC §7).

The server runs every code figure with three injected names
(``services/figure/groups.code_group_globals``):

* ``depictio_group_kwargs`` — ``{}`` unless the reader groups the figure;
* ``depictio_group_by``     — ``[]`` likewise;
* ``depictio_category_colors`` — the dashboard's colour per category.

Templates read them in the prologue (``grp = depictio_group_by[0] if
depictio_group_by else 'habitat'``, ``colors = depictio_group_kwargs.get(...)
or depictio_category_colors.get('habitat') or {}``) — names the transpiler took
for data frames, refusing 11 of the 26 seed figures with "fig line mixes
several prologue frames". A bundle is exported at the default, ungrouped state,
where all three are constants, so they fold: the scalars they produce are
substituted into the code and their assignments dropped, leaving only the
frame-producing prologue and a ``px`` call with literal kwargs — the shape the
transpiler and the bind-and-refill hypothesis already read.

The folding is deliberately small: names bound to literals, ``x[i]`` /
``.get(k, d)`` on literals, ``a if t else b`` / ``and`` / ``or`` / ``not`` on
literals, ``[*[], ...]`` and ``**{}`` spreads, and — when the collection's
columns are known — ``'col' in df.columns``. Anything it cannot decide is left
as written, so the transpiler's refusal stands. Folding never changes what the
code computes at the default state: every rewrite is an evaluation the
interpreter would have made with the same values.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from typing import Any

#: The injected names and their value at the default (ungrouped) state.
CONTEXT_NAMES = ("depictio_group_kwargs", "depictio_group_by", "depictio_category_colors")

_LITERAL_TYPES = (str, int, float, bool, type(None), list, dict, tuple)


class _Unknown(Exception):
    """Raised inside the folder for anything not decidable at export."""


def _is_literal(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return all(_is_literal(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_literal(v) for k, v in value.items())
    return isinstance(value, _LITERAL_TYPES)


def _to_ast(value: Any) -> ast.expr:
    return ast.parse(repr(value), mode="eval").body


class _Folder(ast.NodeTransformer):
    def __init__(self, env: dict[str, Any], columns: frozenset[str] | None) -> None:
        self.env = env
        self.columns = columns

    # -- evaluation -----------------------------------------------------------

    def value(self, node: ast.expr) -> Any:
        """The constant ``node`` evaluates to, or raise ``_Unknown``."""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.env:
                return self.env[node.id]
            raise _Unknown
        if isinstance(node, (ast.List, ast.Tuple)):
            out: list[Any] = []
            for elt in node.elts:
                if isinstance(elt, ast.Starred):
                    out.extend(self.value(elt.value))
                else:
                    out.append(self.value(elt))
            return out if isinstance(node, ast.List) else tuple(out)
        if isinstance(node, ast.Dict):
            out_d: dict[Any, Any] = {}
            for k, v in zip(node.keys, node.values, strict=True):
                if k is None:
                    out_d.update(self.value(v))
                else:
                    out_d[self.value(k)] = self.value(v)
            return out_d
        if isinstance(node, ast.Subscript):
            base = self.value(node.value)
            try:
                return base[self.value(node.slice)]
            except (IndexError, KeyError, TypeError) as exc:
                raise _Unknown from exc
        if isinstance(node, ast.IfExp):
            return self.value(node.body) if self.value(node.test) else self.value(node.orelse)
        if isinstance(node, ast.BoolOp):
            result: Any = None
            for i, operand in enumerate(node.values):
                result = self.value(operand)
                last = i == len(node.values) - 1
                if isinstance(node.op, ast.Or) and (result or last):
                    return result
                if isinstance(node.op, ast.And) and (not result or last):
                    return result
            return result
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not self.value(node.operand)
        if isinstance(node, ast.Call):
            pure = self._pure_call(node)
            if pure is not _Unknown:
                return pure
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and not node.keywords
            and 1 <= len(node.args) <= 2
        ):
            base = self.value(node.func.value)
            if not isinstance(base, dict):
                raise _Unknown
            default = self.value(node.args[1]) if len(node.args) == 2 else None
            return base.get(self.value(node.args[0]), default)
        if (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], (ast.In, ast.NotIn))
            and self.columns is not None
            and isinstance(node.comparators[0], ast.Attribute)
            and node.comparators[0].attr == "columns"
            and isinstance(node.comparators[0].value, ast.Name)
            and node.comparators[0].value.id == "df"
        ):
            present = self.value(node.left) in self.columns
            return present if isinstance(node.ops[0], ast.In) else not present
        raise _Unknown

    def _pure_call(self, node: ast.Call) -> Any:
        """A side-effect-free builtin over literals (``list(dict.fromkeys(...))``,
        ``dict(a, **b)``, ``d.keys()`` / ``.values()`` / ``.items()``), or the
        ``_Unknown`` class when the call is not one of them."""
        try:
            func = node.func
            if isinstance(func, ast.Name) and func.id in ("list", "tuple", "sorted", "dict"):
                args = [self.value(a) for a in node.args]
                kwargs = {kw.arg: self.value(kw.value) for kw in node.keywords if kw.arg}
                spread = [self.value(kw.value) for kw in node.keywords if kw.arg is None]
                if func.id == "dict":
                    out: dict[Any, Any] = dict(*args)
                    for extra in spread:
                        out.update(extra)
                    out.update(kwargs)
                    return out
                if node.keywords:
                    return _Unknown
                return {"list": list, "tuple": tuple, "sorted": sorted}[func.id](*args)
            if isinstance(func, ast.Attribute):
                if (
                    func.attr == "fromkeys"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "dict"
                    and not node.keywords
                ):
                    return dict.fromkeys(*[self.value(a) for a in node.args])
                if func.attr in ("keys", "values", "items") and not node.args and not node.keywords:
                    base = self.value(func.value)
                    if isinstance(base, dict):
                        return list(getattr(base, func.attr)())
        except (_Unknown, TypeError, ValueError):
            return _Unknown
        return _Unknown

    def fold(self, node: ast.expr) -> ast.expr:
        """``node`` as a literal when it evaluates, else with its parts folded."""
        if not isinstance(node, (ast.Constant, ast.Name)) or (
            isinstance(node, ast.Name) and node.id in self.env
        ):
            try:
                value = self.value(node)
            except _Unknown:
                pass
            else:
                if _is_literal(value):
                    return ast.copy_location(_to_ast(value), node)
        return self.visit(node)

    # -- structural rewrites (subtrees that are not wholly constant) ---------

    def visit_Name(self, node: ast.Name) -> ast.expr:
        if (
            node.id in self.env
            and isinstance(node.ctx, ast.Load)
            and _is_literal(self.env[node.id])
        ):
            return ast.copy_location(_to_ast(self.env[node.id]), node)
        return node

    def visit_IfExp(self, node: ast.IfExp) -> ast.expr:
        try:
            test = self.value(node.test)
        except _Unknown:
            return self.generic_visit(node)
        return self.fold(node.body if test else node.orelse)

    def visit_List(self, node: ast.List) -> ast.expr:
        elts: list[ast.expr] = []
        for elt in node.elts:
            if isinstance(elt, ast.Starred):
                try:
                    spread = self.value(elt.value)
                except _Unknown:
                    elts.append(self.generic_visit(elt))
                    continue
                elts.extend(_to_ast(v) for v in spread)
            else:
                elts.append(self.fold(elt))
        node.elts = elts
        return node

    def visit_Call(self, node: ast.Call) -> ast.expr:
        node.func = self.visit(node.func)
        node.args = [self.fold(a) if not isinstance(a, ast.Starred) else a for a in node.args]
        keywords: list[ast.keyword] = []
        for kw in node.keywords:
            if kw.arg is None:
                # `**depictio_group_kwargs` — spread a constant dict as keywords.
                try:
                    spread = self.value(kw.value)
                except _Unknown:
                    keywords.append(kw)
                    continue
                if isinstance(spread, dict):
                    keywords.extend(ast.keyword(arg=k, value=_to_ast(v)) for k, v in spread.items())
                    continue
                keywords.append(kw)
            else:
                kw.value = self.fold(kw.value)
                keywords.append(kw)
        node.keywords = keywords
        return node


def fold_context(
    code: str,
    category_colors: Mapping[str, Any] | None = None,
    columns: Iterable[str] | None = None,
) -> str:
    """``code`` with the injected context folded at the default state.

    Returns the code unchanged when it names none of the injected names, does
    not parse, or nothing folds. ``columns`` (the collection's schema) lets a
    ``'x' in df.columns`` guard fold; without it the guard is left alone.
    """
    if not code or not any(name in code for name in CONTEXT_NAMES):
        return code
    try:
        module = ast.parse(code)
    except SyntaxError:
        return code
    env: dict[str, Any] = {
        "depictio_group_kwargs": {},
        "depictio_group_by": [],
        "depictio_category_colors": dict(category_colors or {}),
    }
    folder = _Folder(env, frozenset(columns) if columns is not None else None)
    body: list[ast.stmt] = []
    for stmt in module.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id != "fig"
        ):
            name = stmt.targets[0].id
            try:
                value = folder.value(stmt.value)
            except _Unknown:
                value = _Unknown
            if value is not _Unknown and _is_literal(value):
                # A scalar the context decided: substitute it, drop the line.
                env[name] = value
                continue
            env.pop(name, None)
            stmt.value = folder.fold(stmt.value)
            body.append(stmt)
            continue
        body.append(folder.visit(stmt))
    module.body = body
    ast.fix_missing_locations(module)
    try:
        return ast.unparse(module)
    except Exception:
        return code
