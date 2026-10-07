import json, os, subprocess, sys
from pathlib import Path
root=Path(__file__).resolve().parent
env=dict(os.environ,PYTHONPATH=str(root/'vendor'))
question='Does the reconstruction reproduce the source workbook and respond correctly to a higher stable return on capital?'
finding=('All requested baseline metrics match source workbook cached results and 56 changed-input cases match independently evaluated source formulas. Raising stable ROC from 0.12 to 0.132 lowers terminal reinvestment and raises per-share value from 66.7825642215609 to 71.97308385937993; gap: 5.190519637819023. This is an implementation probe, not an investment recommendation.')
argv=[sys.executable,'-S','-m','burr','-C',str(root/'model'),'next','fcff','--json','--patch',str(root/'model/probe.yaml'),'--question',question,'--finding',finding,'--deliverable','excel','--output',str(root/'output/baseline.xlsx')]
log=[]
for step in range(8):
    done=subprocess.run(argv,cwd=root,env=env,text=True,capture_output=True)
    assert done.returncode==0,(done.stdout,done.stderr)
    state=json.loads(done.stdout);log.append({'argv':argv,'result':state})
    print('state',state.get('state'))
    if state.get('complete'):break
    action=state.get('action')
    assert action,(state.get('required_inputs'),state.get('diagnostics'))
    cmd=list(action['argv']);cmd.insert(1,'-S')
    done=subprocess.run(cmd,cwd=root,env=env,text=True,capture_output=True)
    assert done.returncode==0,(done.stdout,done.stderr)
    log.append({'argv':cmd,'result':json.loads(done.stdout)})
    argv=list(state['resume_argv']);argv.insert(1,'-S')
else:raise RuntimeError('Workflow incomplete')
(root/'workflow-record.json').write_text(json.dumps(log,indent=2)+'\n')
