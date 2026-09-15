import json
import shutil
import subprocess
from pathlib import Path

import pytest

from burr.cli import main
from burr.dashboard import dashboard_data, emit_dashboard
from burr.errors import BurrError
from burr.model import Workspace
from burr.operations import prepare
from conftest import edit_yaml

ASSETS = Path(__file__).resolve().parents[1] / 'burr' / 'dashboard_assets'


def browser(data, overrides=None):
    if not shutil.which('node'):
        pytest.skip('Node required for browser engine parity')
    script = (ASSETS / 'engine.js').read_text() + '''
const fs=require('fs');const {data,overrides}=JSON.parse(fs.readFileSync(0,'utf8'));
try { console.log(JSON.stringify({result:evaluateDashboard(data,overrides),patch:dashboardPatch(data,overrides)})); }
catch(error) {console.log(JSON.stringify({error:error.message}));}
'''
    return json.loads(subprocess.run(['node', '-e', script], input=json.dumps({'data': data, 'overrides': overrides or {}}),
                                     text=True, capture_output=True, check=True).stdout)


def assert_same(actual, model):
    for key, values in model.run().items():
        assert actual['lines'][key] == pytest.approx(values, rel=1e-11, abs=1e-9)
    for key, value in model.value().items():
        assert actual['value'][key] == pytest.approx(value, rel=1e-11, abs=1e-9)


@pytest.mark.parametrize('fixture', ['workspace', 'recurrence'])
def test_browser_matches_engine_and_replayable_patch(request, fixture):
    workspace = request.getfixturevalue(fixture)
    for scenario in ['base', 'bear']:
        data = dashboard_data(workspace, scenario)
        assert_same(browser(data)['result'], workspace.model(scenario))
        changed = browser(data, {'bindings.price': 3.12, 'valuation.wacc': .23})
        _, trial, _ = prepare(workspace, changed['patch'], scenario)
        assert_same(changed['result'], trial)


@pytest.fixture
def profiled_workspace(workspace):
    def profiles(doc):
        doc['bindings']['cost_pct'] = {'start': .40, 'end': .45}
        doc['valuation']['wacc'] = {'start': .20, 'end': .18}
        doc['scenarios']['bear']['bindings']['cup_growth'] = {'start': .02, 'end': .01}
        doc['scenarios']['bear']['bindings']['cost_pct'] = {'start': .50, 'end': .55}
    edit_yaml(workspace.params_file, profiles)
    return Workspace(workspace.company)


def test_year_specific_inputs_match_python(profiled_workspace):
    workspace = profiled_workspace
    for scenario in ['base', 'bear']:
        data = dashboard_data(workspace, scenario)
        assert_same(browser(data)['result'], workspace.model(scenario))
        changed = browser(data, {'bindings.cup_growth@2028': .05, 'bindings.cost_pct@2029': .42,
                                 'valuation.wacc@2027': .18, 'valuation.terminal_growth': .02})
        _, trial, _ = prepare(workspace, changed['patch'], scenario)
        assert_same(changed['result'], trial)
        assert changed['patch']['bindings']['cup_growth'][0] == data['inputs']['cup_growth'][0]


def test_invalid_trials_never_return_values(workspace):
    data = dashboard_data(workspace)
    for overrides in ({'valuation.shares': 0}, {'valuation.wacc': -.9999, 'valuation.terminal_growth': 0},
                      {'bindings.price': -1}, {'unknown': 4}):
        assert 'error' in browser(data, overrides)
    assert 'error' in browser(data, {'valuation.wacc': -1})


def test_scalar_seed_and_division_errors(workspace):
    edit_yaml(workspace.root / 'templates/lemonade.yaml', lambda d: d['lines'].update({'ratio': 'revenue / profit'}))
    data = dashboard_data(Workspace(workspace.company))
    assert 'error' in browser(data, {'bindings.cost_pct': 1})


def test_bounds_facts_safe_html_and_determinism(workspace, tmp_path):
    data = dashboard_data(workspace, sliders=['price=1:4:.1'])
    assert next(c for c in data['controls'] if c['key'] == 'bindings.price')['enabled']
    assert not any(c['name'] == 'cups0' for c in data['controls'])
    for spec in ['cups0=0:2000:1', 'price=3:4:.1', 'price=1:4:0', 'price=nan:4:1', 'price=nope']:
        with pytest.raises(BurrError): dashboard_data(workspace, sliders=[spec])
    edit_yaml(workspace.params_file, lambda d: d['bindings'].update({'price': {'value': 2.5, 'rationale': '</script><script>alert(1)</script>'}}))
    workspace = Workspace(workspace.company)
    path = tmp_path / 'dashboard.html'
    emit_dashboard(workspace, path, title='<img src=x onerror=alert(1)>')
    first = path.read_text()
    assert '<img src=x' not in first and '</script><script>alert' not in first
    assert '\\u003c/script' in first and 'https://' not in first
    emit_dashboard(workspace, path, title='<img src=x onerror=alert(1)>')
    assert first == path.read_text()
    with pytest.raises(BurrError): emit_dashboard(workspace, tmp_path/'bad.svg')


def test_cli_and_failure_preserve_existing_output(workspace, tmp_path, capsys):
    path = tmp_path / 'dashboard.html'
    assert main(['dashboard', str(workspace.company), '--slider', 'price=1:4:.1', '-o', str(path), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['controls'] > 0
    previous = path.read_bytes()
    assert main(['dashboard', str(workspace.company), '--slider', 'missing=1:4:.1', '-o', str(path)]) == 2
    assert path.read_bytes() == previous
    assert main(['dashboard', str(workspace.company), '-o', str(workspace.params_file)]) == 1


def test_history_uses_exact_preforecast_observations(workspace):
    with (workspace.company / 'actuals.csv').open('a') as stream:
        stream.write('2023,profit,-25\n2025,profit,0\n2027,profit,999\n2024,reported_profit,123\n')
    workspace = Workspace(workspace.company)
    for scenario in ['base', 'bear']:
        data = dashboard_data(workspace, scenario)
        assert data['history']['profit'] == [
            {'period': 2023, 'line': 'profit', 'value': -25},
            {'period': 2025, 'line': 'profit', 'value': 0},
        ]
        assert data['history']['revenue'] == [r for r in workspace.actuals if r['line'] == 'revenue']
        assert data['history_source'] == 'companies/stand/actuals.csv'


def test_history_absent_and_reported_actuals(workspace):
    data = dashboard_data(workspace)
    assert [r['period'] for r in data['history']['revenue']] == [2025, 2026]
    assert data['history']['revenue'] == [r for r in workspace.actuals if r['line'] == 'revenue']
    assert data['history']['profit'] == []  # Revenue observations do not supply profit history.


@pytest.mark.parametrize('mode,value', [('shift', .02), ('level', .05), ('target', .08)])
def test_whole_forecast_changes_and_patch_parity(profiled_workspace, mode, value):
    workspace = profiled_workspace
    for scenario in ['base', 'bear']:
        data = dashboard_data(workspace, scenario)
        key = 'bindings.cup_growth' + ('' if mode == 'shift' else '~' + mode)
        changed = browser(data, {key: value})
        saved = data['inputs']['cup_growth']
        expected = ([v+value for v in saved] if mode == 'shift' else [value]*len(saved) if mode == 'level'
                    else [v+(value-saved[-1])*i/(len(saved)-1) for i,v in enumerate(saved)])
        assert changed['patch']['bindings']['cup_growth'] == pytest.approx(expected)
        _, trial, _ = prepare(workspace, changed['patch'], scenario)
        assert_same(changed['result'], trial)
        if mode == 'target':
            assert expected[0] == saved[0]
            assert expected[-1] == pytest.approx(value)


def test_profile_modes_identity_overlap_and_cli(workspace):
    data = dashboard_data(workspace, sliders=['cup_growth=-.05:.05:.001'])
    assert next(c for c in data['controls'] if c['key'] == 'bindings.cup_growth')['enabled']
    assert browser(data, {'bindings.cup_growth': 0})['patch'] == {}
    assert browser(data, {'bindings.cup_growth~target': data['inputs']['cup_growth'][-1]})['patch'] == {}
    level = data['inputs']['cup_growth'][-1]
    assert browser(data, {'bindings.cup_growth~level': level})['patch']['bindings']['cup_growth'] == [level]*3
    for overrides in [
        {'bindings.cup_growth': .01, 'bindings.cup_growth@2028': .04},
        {'bindings.cup_growth@2028': .04, 'bindings.cup_growth': .01},
    ]:
        changed = browser(data, overrides)
        assert changed['patch']['bindings']['cup_growth'][1] == .04
        _, trial, _ = prepare(workspace, changed['patch'])
        assert_same(changed['result'], trial)
    assert 'error' in browser(data, {'bindings.cup_growth': .02, 'bindings.cup_growth~level': .03})
    with pytest.raises(BurrError):
        dashboard_data(workspace, sliders=['cup_growth=-.1:.1:.01', 'cup_growth@2028=0:.2:.01'])
