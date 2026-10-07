#!/usr/bin/env python3
"""Reconstruct the selected Damodaran FCFF model using Burr's formula engine."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
import tempfile

PACKET = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKET / 'vendor'))
import yaml
from burr import ENGINE_VERSION, SCHEMA_VERSION
from burr.model import Workspace
from burr.workbook import emit

CELLS = {
 'beta':'D52', 'capex0':'D22', 'cash':'D28', 'debt':'F38',
 'debt_cost':'E56', 'depreciation0':'D23', 'ebit0':'D20',
 'high_years':'E43', 'options':'D29', 'prior_book_debt':'E30',
 'prior_book_equity':'E31', 'revenue0':'D25', 'risk_premium':'D54',
 'riskfree':'D53', 'share_price':'F36', 'shares':'F37',
 'stable_growth':'E79', 'stable_roc':'F101', 'tax_rate':'D24',
 'working_capital0':'D26', 'working_capital_change0':'D27',
}
RATIOS = {'beta','debt_cost','risk_premium','riskfree','stable_growth','stable_roc','tax_rate'}
LINES = {
 'horizon': 'high_years',
 'cost_of_equity': 'riskfree + beta * risk_premium',
 'equity_weight': 'share_price * shares / (debt + share_price * shares)',
 'debt_weight': '1 - equity_weight',
 'after_tax_debt_cost': 'debt_cost * (1 - tax_rate)',
 'wacc': 'cost_of_equity * equity_weight + after_tax_debt_cost * debt_weight',
 'return_on_capital': 'ebit0 * (1 - tax_rate) / (prior_book_debt + prior_book_equity)',
 'reinvestment_rate': '(capex0 - depreciation0 + working_capital_change0) / (ebit0 * (1 - tax_rate))',
 'high_growth': 'return_on_capital * reinvestment_rate',
 'working_capital_ratio': 'maximum(working_capital0 / revenue0, 0)',
 'growth': 'high_phase * high_growth + (1 - high_phase) * stable_growth',
 'nopat': 'grow(ebit0 * (1 - tax_rate), growth)',
 'revenue': 'grow(revenue0, growth)',
 'working_capital_change': 'delta(revenue, revenue0) * working_capital_ratio',
 'capex_high': 'grow(capex0, high_growth)',
 'depreciation_high': 'grow(depreciation0, high_growth)',
 'net_capex': 'high_phase * (capex_high - depreciation_high) + (1 - high_phase) * (stable_growth / stable_roc * nopat - working_capital_change)',
 'fcff': 'nopat - net_capex - working_capital_change',
 'discount_factor': 'grow(1, wacc)',
 'pv_fcff': 'fcff / discount_factor',
 'cumulative_pv_fcff': 'lag(cumulative_pv_fcff, 0 * cash) + pv_fcff',
 'terminal_value': 'nopat * (1 + stable_growth) * (1 - stable_growth / stable_roc) / (wacc - stable_growth)',
 'pv_terminal': 'terminal_value / discount_factor',
 'enterprise_value': 'cumulative_pv_fcff + pv_terminal',
 'equity_before_options': 'enterprise_value + cash - debt',
 'equity_after_options': 'equity_before_options - options',
 'per_share': 'equity_after_options / shares',
 'net_cash_after_options': 'cash - debt - options',
}

def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))

def construct(inputs, directory):
    if set(inputs) != set(CELLS):
        raise ValueError('Inputs must contain exactly the baseline contract keys')
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in inputs.values()):
        raise ValueError('Inputs must be finite numbers')
    if inputs['high_years'] != 5:
        raise ValueError('The task fixes the high-growth horizon at five years')
    directory = Path(directory).resolve()
    company = directory / 'companies' / 'fcff'
    company.mkdir(parents=True, exist_ok=True)
    (company / 'experiments').mkdir(exist_ok=True)
    (company / 'scenarios').mkdir(exist_ok=True)
    dump(directory / 'burr.lock', {'engine_version': ENGINE_VERSION, 'schema_version': SCHEMA_VERSION})
    parameters = []
    bindings = {}
    for key, cell in CELLS.items():
        unit = 'ratio' if key in RATIOS else ('count' if key in {'shares','high_years'} else 'currency')
        parameters.append({'name': key, 'unit': unit, 'doc': f'Source workbook NewFCFF2Stage!{cell}'})
        bindings[key] = {'value': inputs[key], 'source': f'source.xlsx:NewFCFF2Stage!{cell}',
            'rationale': 'Supplied model input; source workbook assumption, not independently verified financial fact.'}
    parameters.append({'name':'high_phase','unit':'ratio','doc':'One for five high-growth years, zero for terminal year'})
    bindings['high_phase'] = {'value': [1,1,1,1,1,0],
        'source':'Source workbook E43 and N133', 'rationale':'Five explicit high-growth years plus the first stable year.'}
    dump(directory / 'templates' / 'two_stage_fcff.yaml', {
        'template':'two_stage_fcff',
        'doc':'Selected Damodaran two-stage FCFF switches, with terminal cash flow explicitly visible in sixth column.',
        'parameters':parameters, 'lines':LINES,
        'checks':['horizon == 5', 'shares > 0', 'wacc > stable_growth', 'stable_growth > -1'],
    })
    params = {'entity':'fcff','template':'two_stage_fcff','periods':'1..6','base_year':0,'bindings':bindings}
    # No independently verified financial observations were supplied.
    (company / 'actuals.csv').write_text('period,line,value\n')
    dump(company / 'params.yaml', params)
    # Burr computes capital costs and net cash. The adapter only copies these
    # computed assumptions into the native DCF configuration, which accepts
    # numeric value forms rather than references to formula lines.
    initial = Workspace(company).model()
    initial.validate()
    computed = initial.run()
    params['valuation'] = {
        'fcf':'fcff',
        'wacc':{'value':computed['wacc'][0], 'source':'Burr wacc formula line',
                'rationale':'Same capital cost in high and stable phases under selected switches.'},
        'terminal_growth':{'value':inputs['stable_growth'],'source':'source.xlsx:NewFCFF2Stage!E79'},
        'shares':{'value':inputs['shares'],'source':'source.xlsx:NewFCFF2Stage!F37'},
        'net_cash':{'value':computed['net_cash_after_options'][0],
                    'source':'Burr net_cash_after_options formula line',
                    'rationale':'Cash minus market debt minus option value; native DCF equity is after options.'},
    }
    dump(company / 'params.yaml', params)
    return Workspace(company)

def calculate(inputs, workspace, excel):
    ws = construct(inputs, workspace)
    model = ws.model()
    model.validate()
    lines = model.run()
    value = model.value()
    # Native Burr DCF explicitly includes year 6, then values year 7 onward.
    # This is algebraically identical to valuing year 6 onward at year 5.
    for actual, expected in [(value['ev'], lines['enterprise_value'][4]),
                             (value['per_share'], lines['per_share'][4])]:
        if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8):
            raise ArithmeticError('Native Burr DCF and five-year source valuation disagree')
    output = {key: [lines[key][0]] for key in (
        'after_tax_debt_cost','cost_of_equity','debt_weight','high_growth','wacc','working_capital_ratio')}
    for key in ('fcff','net_capex','nopat','working_capital_change'):
        output[key] = list(lines[key])
    output['pv_fcff'] = list(lines['pv_fcff'][:5])
    for key in ('equity_before_options','per_share','pv_terminal','terminal_value'):
        output[key] = [lines[key][4]]
    output['ev'] = [value['ev']]
    if not all(math.isfinite(number) for values in output.values() for number in values):
        raise ArithmeticError('Nonfinite result')
    Path(excel).parent.mkdir(parents=True, exist_ok=True)
    emit(model, Path(excel))
    return output

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--excel', type=Path)
    args = parser.parse_args()
    inputs = json.loads(args.inputs.read_text())
    if args.workspace is None:
        runs = PACKET / 'runs'
        runs.mkdir(exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix='fcff-',dir=runs))
    else:
        workspace = args.workspace
    excel = args.excel or workspace / 'output' / 'valuation.xlsx'
    result = calculate(inputs, workspace, excel)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')

if __name__ == '__main__':
    main()
