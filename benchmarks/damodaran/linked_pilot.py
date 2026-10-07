"""Create a corrected copy of the pilot workspace, preserving its original evidence.

Run: python -m benchmarks.damodaran.linked_pilot --output NEW_DIRECTORY
The historical agent submission and its reported scores remain unchanged.
"""

import argparse
from pathlib import Path
import shutil

from burr.model import Workspace
from burr.operations import coherent
from burr.storage import read_yaml, yaml_text

SOURCE = Path(__file__).parent / "agent_pilot/submissions/burr/model"
LINKS = {"wacc": "wacc", "terminal_growth": "stable_growth",
         "shares": "shares", "net_cash": "net_cash_after_options"}


def create(output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Use a new workspace: {output}")
    shutil.copytree(SOURCE, output)
    path = output / "companies/fcff/params.yaml"
    params = read_yaml(path)
    for name, target in LINKS.items():
        params["valuation"][name] = {
            "ref": target,
            "source": f"Burr model {'line' if name in {'wacc', 'net_cash'} else 'binding'}: {target}",
            "rationale": "Resolve from the current scenario; never copy a computed valuation assumption.",
        }
    path.write_text(yaml_text(params))
    workspace = Workspace(path.parent)
    coherent(workspace)
    m = workspace.model()
    if abs(m.value()["per_share"] - m.run()["per_share"][4]) > 1e-7:
        raise ValueError("Linked native DCF disagrees with the source-boundary formula")
    return workspace


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    workspace = create(args.output)
    print(workspace.company)
