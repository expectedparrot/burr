import pytest

from burr.model import Workspace
from burr.starter import init
from burr.storage import read_yaml, yaml_text


@pytest.fixture
def workspace(tmp_path):
    init(tmp_path / "workspace")
    return Workspace(tmp_path / "workspace" / "companies" / "stand")


def edit_yaml(path, edit):
    document = read_yaml(path)
    edit(document)
    path.write_text(yaml_text(document))


@pytest.fixture
def recurrence(workspace):
    def template(doc):
        doc["parameters"].extend([{"name": "cash0", "unit": "currency"}, {"name": "cap", "unit": "currency"}])
        doc["lines"].update({
            "cash": "lag(cash, cash0) + profit",
            "change": "delta(cash, cash0)",
            "limited": "clip(abs(change), cash0, cap)",
            "small": "minimum(cash, cap)",
            "large": "maximum(cash, cap)",
            "ebitda": "profit",
        })
        doc["checks"].extend(["change >= 0", "limited <= cap"])
    edit_yaml(workspace.root / "templates" / "lemonade.yaml", template)
    edit_yaml(workspace.params_file, lambda doc: doc["bindings"].update({"cash0": 0, "cap": 2000}))
    return Workspace(workspace.company)
