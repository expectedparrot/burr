"""A small, complete starter workspace."""

import os
import shutil
import tempfile
from pathlib import Path

from . import ENGINE_VERSION, SCHEMA_VERSION
from .errors import require
from .storage import identifier, yaml_text

TEMPLATE = """# LOGIC: business constants belong in params.yaml.
template: {name}
doc: A lemonade stand with volume, price, and variable costs.
parameters:
  - {{name: cups0, unit: count, doc: Base-year cups sold}}
  - {{name: cup_growth, unit: ratio, doc: Annual volume growth}}
  - {{name: price, unit: currency, doc: Price per cup}}
  - {{name: cost_pct, unit: ratio, doc: Variable costs as a fraction of revenue}}
lines:
  cups: grow(cups0, cup_growth)
  revenue: cups * price
  profit: revenue * (1 - cost_pct)
checks:
  - profit <= revenue
  - revenue >= 0
"""

PARAMS = """# OPINIONS: value forms can carry rationale, source, confidence, and as_of.
entity: stand
template: {name}
periods: 2027..2029
base_year: 2026
bindings:
  cups0: {{value: 1000, source: last summer's tally}}
  cup_growth: {{start: 0.10, end: 0.05, rationale: word of mouth fades}}
  price: 2.50
  cost_pct: {{dist: normal, mean: 0.40, sd: 0.05, lo: 0.2, hi: 0.7}}
valuation:
  fcf: profit
  wacc: 0.20
  terminal_growth: 0.0
  shares: 2
scenarios:
  bear:
    thesis: Foot traffic slows and supply costs rise.
    bindings:
      cup_growth: 0.02
      cost_pct: 0.50
"""

ACTUALS = "period,line,value\n2025,cups,900\n2025,revenue,2160\n2026,cups,1000\n2026,revenue,2500\n"


def init(directory, name="lemonade"):
    identifier(name)
    target = Path(directory)
    require(not target.exists() or target.is_dir() and not any(target.iterdir()),
            "patch_conflict", "init requires an absent or empty directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".burr-init-", dir=target.parent))
    try:
        (staged / "templates").mkdir()
        company = staged / "companies" / "stand"
        (company / "scenarios").mkdir(parents=True)
        (company / "experiments").mkdir()
        (staged / "burr.lock").write_text(yaml_text({"engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION}))
        (staged / "templates" / f"{name}.yaml").write_text(TEMPLATE.format(name=name))
        (company / "params.yaml").write_text(PARAMS.format(name=name))
        (company / "actuals.csv").write_text(ACTUALS)
        from .model import Workspace
        from .operations import coherent
        coherent(Workspace(company))
        os.replace(staged, target)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return {"ok": True, "workspace": str(target), "company": "companies/stand", "template": name}
