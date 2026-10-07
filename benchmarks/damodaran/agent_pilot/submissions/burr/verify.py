"""Development-only independent evaluator of the actual source Excel formulas."""
import json, math, re, random
from pathlib import Path
import openpyxl
from submission import CELLS, calculate

SOURCE = openpyxl.load_workbook('source.xlsx', data_only=False)['NewFCFF2Stage']
CACHED = openpyxl.load_workbook('source.xlsx', data_only=True)['NewFCFF2Stage']
CONTRACT = json.loads(Path('contract.json').read_text())
BASE = json.loads(Path('baseline.json').read_text())

def source_eval(inputs):
    overrides = {CELLS[k]: v for k,v in inputs.items()}
    cache = dict(overrides)
    def cell(address):
        address = address.replace('$','')
        if address in cache: return cache[address]
        value = SOURCE[address].value
        answer = parse(value[1:]) if isinstance(value,str) and value.startswith('=') else (0 if value is None else value)
        cache[address] = answer
        return answer
    def parse(formula):
        tokens = re.findall(r'"[^"]*"|\$?[A-Z]+\$?\d+|[A-Z]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?|<=|>=|<>|[+*/^=<>(),:-]', formula)
        index=0
        def expression(minimum=0):
            nonlocal index
            token=tokens[index]; index+=1
            if token=='(':
                left=expression(); assert tokens[index]==')'; index+=1
            elif token=='-': left=('neg',expression(5))
            elif token.startswith('"'): left=('str',token[1:-1])
            elif re.fullmatch(r'\$?[A-Z]+\$?\d+',token):
                if index<len(tokens) and tokens[index]==':':
                    index+=1; right=tokens[index];index+=1;left=('range',token,right)
                else:left=('cell',token)
            elif token in ('IF','SUM'):
                assert tokens[index]=='(';index+=1;args=[expression()]
                while tokens[index]==',':index+=1;args.append(expression())
                assert tokens[index]==')';index+=1;left=(token,*args)
            else:left=('number',float(token))
            precedence={'=':1,'<':1,'>':1,'<=':1,'>=':1,'<>':1,'+':2,'-':2,'*':3,'/':3,'^':4}
            while index<len(tokens) and precedence.get(tokens[index],-1)>=minimum:
                op=tokens[index];index+=1;level=precedence[op]
                right=expression(level if op=='^' else level+1)
                left=(op,left,right)
            return left
        tree=expression();assert index==len(tokens),(formula,tokens[index:])
        def evaluate(node):
            op=node[0]
            if op in ('number','str'):return node[1]
            if op=='cell':return cell(node[1])
            if op=='range':
                return [cell(c.coordinate) for row in SOURCE[node[1].replace('$',''):node[2].replace('$','')] for c in row]
            if op=='IF':return evaluate(node[2] if evaluate(node[1]) else node[3])
            if op=='SUM':
                values=[]
                for arg in node[1:]:
                    v=evaluate(arg);values.extend(v if isinstance(v,list) else [v])
                return sum(v for v in values if isinstance(v,(int,float)))
            if op=='neg':return -evaluate(node[1])
            a,b=evaluate(node[1]),evaluate(node[2])
            # Excel orders strings above numbers in direct comparisons.
            if op in ('<','>','<=','>=') and isinstance(a,str)!=isinstance(b,str):
                a,b=(1 if isinstance(a,str) else 0),(1 if isinstance(b,str) else 0)
            return {'+':lambda:a+b,'-':lambda:a-b,'*':lambda:a*b,'/':lambda:a/b,'^':lambda:a**b,
                    '=':lambda:a==b,'<>':lambda:a!=b,'<':lambda:a<b,'>':lambda:a>b,'<=':lambda:a<=b,'>=':lambda:a>=b}[op]()
        return evaluate(tree)
    return {k:[cell(c) for c in spec['source_cells']] for k,spec in CONTRACT['outputs'].items()}

def compare(actual,expected):
    assert actual.keys()==expected.keys()
    maximum=0
    for key,values in expected.items():
        assert len(actual[key])==len(values)
        for a,b in zip(actual[key],values):
            assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8),(key,a,b)
            maximum=max(maximum,abs(a-b)/max(1,abs(b)))
    return maximum

def main():
    cached={k:[CACHED[c].value for c in spec['source_cells']] for k,spec in CONTRACT['outputs'].items()}
    source=source_eval(BASE)
    baseline=json.loads(Path('baseline-output.json').read_text())
    report={'cached_source_relative_error':compare(source,cached),
            'baseline_relative_error':compare(baseline,cached),'cases':[]}
    cases=[]
    for field in BASE:
        if field=='high_years':continue
        for factor in (0.9,1.1):
            x=dict(BASE);x[field]*=factor;cases.append((f'{field}*{factor}',x))
    x=dict(BASE);x['working_capital0']=-100;cases.append(('negative_working_capital',x))
    x=dict(BASE);x['working_capital0']=0;cases.append(('zero_working_capital',x))
    x=dict(BASE);x['stable_growth']=0;cases.append(('zero_stable_growth',x))
    x=dict(BASE);x['stable_roc']=0.04;cases.append(('negative_terminal_fcff',x))
    rng=random.Random(704)
    for i in range(12):
        x={k:(v if k=='high_years' else v*rng.uniform(.92,1.08)) for k,v in BASE.items()}
        cases.append((f'combined_{i}',x))
    for i,(name,x) in enumerate(cases):
        actual=calculate(x, Path('verification')/f'case_{i}'/'model', Path('verification')/f'case_{i}'/'export.xlsx')
        err=compare(actual,source_eval(x))
        report['cases'].append({'name':name,'maximum_relative_error':err,'pass':True})
    report['passed_cases']=len(cases)
    Path('verification-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed_cases':len(cases),'maximum_relative_error':max(c['maximum_relative_error'] for c in report['cases'])}))
if __name__=='__main__':main()
