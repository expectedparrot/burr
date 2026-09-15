"""Resolution of value forms; all random draws are explicitly supplied."""

import math

from .errors import BurrError, require
from .storage import METADATA, VALUE_KEYS

UNITS = {"currency_m", "currency", "count", "ratio", "per_period_ratio"}


def number(value):
    require(isinstance(value, (int, float)) and not isinstance(value, bool), "eval_error",
            f"expected a number, got {value!r}")
    result = float(value)
    require(math.isfinite(result), "eval_error", "values must be finite")
    return result


def periods(value):
    if isinstance(value, str) and ".." in value:
        try:
            start, end = map(int, value.split(".."))
        except ValueError as exc:
            raise BurrError("eval_error", "periods must be START..END") from exc
        require(0 <= end - start < 1000, "length_mismatch", "forecast horizon must contain 1–1000 periods")
        return list(range(start, end + 1))
    require(isinstance(value, list) and value, "length_mismatch", "periods must be START..END or a nonempty year list")
    require(all(isinstance(x, int) and not isinstance(x, bool) for x in value), "eval_error", "periods must be integer years")
    require(len(value) <= 1000 and all(b == a + 1 for a, b in zip(value, value[1:])),
            "length_mismatch", "periods must be consecutive ascending years")
    return value[:]


def resolve(form, years, rng=None):
    if isinstance(form, list):
        require(len(form) == len(years), "length_mismatch",
                f"expected {len(years)} values, got {len(form)}")
        return [number(x) for x in form]
    if not isinstance(form, dict):
        return number(form)
    unknown = set(form) - METADATA - VALUE_KEYS
    require(not unknown, "eval_error", f"unknown value-form keys: {', '.join(sorted(unknown))}")
    if "confidence" in form:
        require(form["confidence"] in ("low", "medium", "high"), "eval_error", "invalid confidence")
    if "unit" in form:
        require(form["unit"] in UNITS, "unit_mismatch", f"unknown unit {form['unit']!r}")
    if "tolerance" in form:
        require(number(form["tolerance"]) >= 0, "eval_error", "tolerance must be nonnegative")
    has_glide = "start" in form or "end" in form
    has_step = "until" in form or "after" in form
    has_dist = "dist" in form
    allowed = set(METADATA)
    if "value" in form:
        allowed.add("value")
    if has_glide:
        allowed |= {"start", "end", "shape"}
    if has_step:
        allowed |= {"until", "after"}
    if has_dist:
        allowed |= {"dist", "lo", "hi"}
        if form["dist"] == "normal":
            allowed |= {"mean", "sd"}
        elif form["dist"] == "uniform":
            allowed |= {"low", "high"}
        if has_glide:
            allowed.add("applies_to")
    require(not set(form) - allowed, "eval_error", f"keys do not belong to this value form: {', '.join(sorted(set(form) - allowed))}")
    require(sum(("value" in form, has_glide, has_step)) <= 1, "eval_error", "conflicting value forms")
    require(not (has_dist and (has_step or "value" in form)), "eval_error", "distribution can only combine with a glide")
    draw = None
    if has_dist:
        if form["dist"] == "normal":
            require("mean" in form and "sd" in form, "eval_error", "normal requires mean and sd")
            mean, sd = number(form["mean"]), number(form["sd"])
            require(sd >= 0, "eval_error", "normal sd must be nonnegative")
            draw = rng.gauss(mean, sd) if rng else mean
        elif form["dist"] == "uniform":
            require("low" in form and "high" in form, "eval_error", "uniform requires low and high")
            low, high = number(form["low"]), number(form["high"])
            require(low <= high, "eval_error", "uniform low must not exceed high")
            draw = rng.uniform(low, high) if rng else (low + high) / 2
        else:
            raise BurrError("eval_error", f"unknown distribution {form['dist']!r}")
        lo = number(form["lo"]) if "lo" in form else -math.inf
        hi = number(form["hi"]) if "hi" in form else math.inf
        require(lo <= hi, "eval_error", "lo must not exceed hi")
        if rng:
            draw = min(hi, max(lo, draw))
    if "value" in form:
        return resolve(form["value"], years, rng)
    if has_glide:
        require("start" in form and "end" in form, "eval_error", "glide requires start and end")
        start, end = number(form["start"]), number(form["end"])
        if has_dist:
            require(form.get("applies_to") in ("start", "end"), "eval_error", "glide distribution requires applies_to: start|end")
            if form["applies_to"] == "start":
                start = draw
            else:
                end = draw
        shape = form.get("shape", "linear")
        require(shape in ("linear", "geometric"), "eval_error", f"unknown glide shape {shape!r}")
        if shape == "geometric":
            require(start != 0 and end / start > 0, "eval_error", "geometric endpoints must have the same nonzero sign")
        if len(years) == 1:
            return [start]
        result = [start + (end - start) * (i / (len(years) - 1)) if shape == "linear"
                  else start * (end / start) ** (i / (len(years) - 1)) for i in range(len(years))]
        result[0], result[-1] = start, end
        return [number(v) for v in result]
    if has_step:
        until = form.get("until")
        require(isinstance(until, dict) and len(until) == 1 and "after" in form,
                "eval_error", "step syntax is {until: {2028: value}, after: value}")
        year, before = next(iter(until.items()))
        try:
            year = int(year)
        except (TypeError, ValueError) as exc:
            raise BurrError("eval_error", "step cutoff must be a year") from exc
        before, after = number(before), number(form["after"])
        return [before if y <= year else after for y in years]
    if has_dist:
        return number(draw)
    raise BurrError("eval_error", "mapping has no value form")


def series(value, length):
    return value if isinstance(value, list) else [value] * length
