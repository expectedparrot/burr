"""Closed AST language, dependency analysis, units, and two evaluation strategies."""

import ast
import math
import operator

from .errors import BurrError, require
from .values import number, series

ARITY = {"grow": 2, "delta": 2, "lag": 2, "minimum": 2, "maximum": 2, "clip": 3, "abs": 1}
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
           ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}
RATIOS = {"ratio", "per_period_ratio"}


def parse(source, *, check=False):
    require(isinstance(source, str), "eval_error", "expressions must be strings")
    require(len(source) <= 10000, "eval_error", "expression is too large")
    try:
        node = ast.parse(source, mode="eval").body
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise BurrError("eval_error", f"invalid expression {source!r}") from exc

    def visit(n):
        if isinstance(n, ast.Constant):
            number(n.value)
            require(check or n.value in (0, 1), "eval_error",
                    "business constants belong in bindings; only structural 0 and 1 are allowed in lines")
        elif isinstance(n, ast.Name):
            require(n.id.isascii() and __import__("re").fullmatch(r"[a-z][a-z0-9_]*", n.id),
                    "unknown_name", f"invalid name {n.id!r}")
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            visit(n.operand)
        elif isinstance(n, ast.BinOp) and type(n.op) in BINARY:
            visit(n.left)
            visit(n.right)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            require(n.func.id in ARITY and not n.keywords and len(n.args) == ARITY.get(n.func.id),
                    "eval_error", f"unknown function or wrong arguments: {n.func.id}")
            for arg in n.args:
                visit(arg)
        else:
            raise BurrError("eval_error", f"unsupported syntax: {ast.dump(n, include_attributes=False)}")

    if check:
        require(isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARE,
                "eval_error", "checks must contain one comparison")
        visit(node.left)
        visit(node.comparators[0])
    else:
        visit(node)
    return node


def dependencies(node, delayed=False):
    """(name, delayed) edges; the seed of lag remains an immediate dependency."""
    if isinstance(node, ast.Name):
        return {(node.id, delayed)}
    if isinstance(node, ast.Call):
        result = set()
        for i, arg in enumerate(node.args):
            result |= dependencies(arg, delayed or (node.func.id == "lag" and i == 0))
        return result
    result = set()
    for child in ast.iter_child_nodes(node):
        result |= dependencies(child, delayed)
    return result


def topological(expressions):
    order, visited, active = [], set(), []

    def visit(name):
        if name in active:
            raise BurrError("circular_dependency", " → ".join(active + [name]), key=name)
        if name in visited:
            return
        active.append(name)
        for dependency, delayed in sorted(dependencies(expressions[name])):
            if dependency in expressions and not delayed:
                visit(dependency)
        active.pop()
        visited.add(name)
        order.append(name)

    for name in sorted(expressions):
        visit(name)
    return order


def infer_unit(node, lookup):
    if isinstance(node, ast.Constant):
        return "ratio"
    if isinstance(node, ast.Name):
        return lookup(node.id)
    if isinstance(node, ast.UnaryOp):
        return infer_unit(node.operand, lookup)

    def compatible(a, b):
        if a is None or b is None:
            return None
        require(a == b or {a, b} <= RATIOS, "unit_mismatch", f"incompatible units: {a} and {b}")
        return a

    if isinstance(node, ast.BinOp):
        a, b = infer_unit(node.left, lookup), infer_unit(node.right, lookup)
        if a is None or b is None:
            return None
        if isinstance(node.op, (ast.Add, ast.Sub)):
            # Zero is the additive identity in any dimension.
            if isinstance(node.left, ast.Constant) and node.left.value == 0:
                return b
            if isinstance(node.right, ast.Constant) and node.right.value == 0:
                return a
            return compatible(a, b)
        require(not ({a, b} == {"currency", "currency_m"}), "unit_mismatch", "currency and currency_m require explicit conversion")
        if isinstance(node.op, ast.Mult):
            if a in RATIOS:
                return b
            if b in RATIOS:
                return a
            if "count" in (a, b) and (a in {"currency", "currency_m"} or b in {"currency", "currency_m"}):
                return b if a == "count" else a
            return f"{a}*{b}"
        if a == b or {a, b} <= RATIOS:
            return "ratio"
        if b in RATIOS or b == "count" and a in {"currency", "currency_m"}:
            return a
        return f"{a}/{b}"
    if isinstance(node, ast.Call):
        units = [infer_unit(a, lookup) for a in node.args]
        if node.func.id == "grow":
            require(units[1] is None or units[1] in RATIOS, "unit_mismatch", "grow requires a ratio growth argument")
            return units[0]
        if node.func.id == "lag" and units[0] is None:
            # A declared seed establishes the dimension of a recurrence's first
            # value; later fixed-point passes check its lagged line against it.
            return units[1]
        if node.func.id == "abs":
            return units[0]
        # Structural zero is a valid bound/seed in any dimension, as in
        # maximum(ebit, 0), clip(cash, 0, limit), or delta(revenue, 0).
        dimensional = [unit for arg, unit in zip(node.args, units)
                       if not (isinstance(arg, ast.Constant) and arg.value == 0)]
        if not dimensional:
            return "ratio"
        unit = dimensional[0]
        for other in dimensional[1:]:
            unit = compatible(unit, other)
        return unit
    if isinstance(node, ast.Compare):
        return compatible(infer_unit(node.left, lookup), infer_unit(node.comparators[0], lookup))


class Evaluator:
    def __init__(self, expressions, inputs, length, order):
        self.expressions, self.inputs, self.length, self.order = expressions, inputs, length, order
        self.cache, self.products = {}, {}

    def scalar(self, node):
        return all(name in self.inputs and not isinstance(self.inputs[name], list)
                   for name, _ in dependencies(node)) and not any(
                       isinstance(n, ast.Call) and n.func.id in {"grow", "lag", "delta"} for n in ast.walk(node))

    def at(self, node, t):
        key = (node, t)
        if key in self.cache:
            return self.cache[key]
        if isinstance(node, ast.Constant):
            result = float(node.value)
        elif isinstance(node, ast.Name):
            if node.id in self.inputs:
                value = self.inputs[node.id]
                result = value[t] if isinstance(value, list) else value
            else:
                result = self.at(self.expressions[node.id], t)
        elif isinstance(node, ast.UnaryOp):
            result = -self.at(node.operand, t)
        elif isinstance(node, ast.BinOp):
            result = BINARY[type(node.op)](self.at(node.left, t), self.at(node.right, t))
        else:
            fn, args = node.func.id, node.args
            if fn in {"lag", "delta"}:
                require(self.scalar(args[1]), "eval_error", f"{fn} base0 must be scalar")
                previous = self.at(args[0], t - 1) if t else self.at(args[1], 0)
                result = previous if fn == "lag" else self.at(args[0], t) - previous
            elif fn == "grow":
                require(self.scalar(args[0]), "eval_error", "grow x0 must be scalar")
                if t and (node, t - 1) not in self.products:
                    self.at(node, t - 1)
                product = (self.products[(node, t - 1)] if t else 1.0) * (1.0 + self.at(args[1], t))
                self.products[key] = product
                result = self.at(args[0], 0) * product
            else:
                values = [self.at(a, t) for a in args]
                result = {"minimum": min, "maximum": max, "abs": abs,
                          "clip": lambda x, lo, hi: min(max(x, lo), hi)}[fn](*values)
        result = number(result)
        self.cache[key] = result
        return result

    def vector(self, node):
        key = (node, "vector")
        if key in self.cache:
            return self.cache[key]
        if isinstance(node, ast.Constant):
            result = [float(node.value)] * self.length
        elif isinstance(node, ast.Name):
            result = series(self.inputs[node.id], self.length) if node.id in self.inputs else self.vector(self.expressions[node.id])
        elif isinstance(node, ast.UnaryOp):
            result = [-x for x in self.vector(node.operand)]
        elif isinstance(node, ast.BinOp):
            result = [BINARY[type(node.op)](a, b) for a, b in zip(self.vector(node.left), self.vector(node.right))]
        else:
            fn, args = node.func.id, node.args
            values = [self.vector(a) for a in args]
            if fn == "grow":
                require(self.scalar(args[0]), "eval_error", "grow x0 must be scalar")
                result, product = [], 1.0
                for growth in values[1]:
                    product *= 1.0 + growth
                    result.append(values[0][0] * product)
            elif fn in {"lag", "delta"}:
                require(self.scalar(args[1]), "eval_error", f"{fn} base0 must be scalar")
                previous = [values[1][0]] + values[0][:-1]
                result = previous if fn == "lag" else [a - b for a, b in zip(values[0], previous)]
            else:
                func = {"minimum": min, "maximum": max, "abs": abs,
                        "clip": lambda x, lo, hi: min(max(x, lo), hi)}[fn]
                result = [func(*v) for v in zip(*values)]
        result = [number(x) for x in result]
        self.cache[key] = result
        return result

    def evaluate(self, *, force_period=False):
        period_mode = force_period or any(isinstance(n, ast.Call) and n.func.id == "lag"
                                         for e in self.expressions.values() for n in ast.walk(e))
        results = {name: [] for name in self.order}
        try:
            if period_mode:
                for t in range(self.length):
                    for name in self.order:
                        results[name].append(self.at(self.expressions[name], t))
            else:
                for name in self.order:
                    results[name] = self.vector(self.expressions[name])
        except (ArithmeticError, ValueError, RecursionError) as exc:
            raise BurrError("eval_error", f"evaluation failed: {exc}", key=name) from exc
        except BurrError as exc:
            exc.diagnostics[0].where["key"] = name
            raise
        return results
