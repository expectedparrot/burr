/* Closed expression interpreter. Shared by the dashboard and parity tests. */
function dashboardInputs(data, overrides = {}) {
  const inputs = structuredClone(data.inputs), valuation = structuredClone(data.valuation);
  const controls = new Map(data.controls.map(c => [c.key, c]));
  const active = Object.entries(overrides).map(([key, value]) => {
    const c = controls.get(key);
    if (!c) throw Error('Unknown assumption: ' + key);
    if (!Number.isFinite(value)) throw Error('Assumptions must be finite numbers.');
    return {c, value};
  });
  const profiles = new Set();
  // Whole-horizon changes first, then explicit annual overrides. This order is
  // independent of insertion order and preserves old saved annual experiments.
  active.sort((a,b) => Number(a.c.index !== null) - Number(b.c.index !== null));
  for (const {c, value} of active) {
    const target = c.section === 'bindings' ? inputs : valuation;
    if (c.profile) {
      const group = c.section + '.' + c.name;
      if (profiles.has(group)) throw Error('Choose one forecast-wide mode for ' + c.name);
      profiles.add(group);
      target[c.name] = c.profile.map((saved, i) => {
        if (c.transform === 'shift') return saved + value;
        if (c.transform === 'level') return value;
        // Phase in the difference from the saved terminal assumption, retaining
        // the saved trajectory and leaving the first forecast year unchanged.
        return saved + (value-c.profile.at(-1)) * (c.profile.length === 1 ? 1 : i/(c.profile.length-1));
      });
    } else if (c.index === null) target[c.name] = value;
    else target[c.name][c.index] = value;
  }
  for (const values of [inputs, valuation]) for (const v of Object.values(values)) {
    if (!(Array.isArray(v) ? v : [v]).every(Number.isFinite)) throw Error('Assumption changes exceed the supported numeric range.');
  }
  return {inputs, valuation};
}

function evaluateDashboard(data, overrides = {}) {
  const {inputs, valuation} = dashboardInputs(data, overrides);
  const finite = x => { if (!Number.isFinite(x)) throw Error('Calculation is not finite. Check your assumptions.'); return x; };
  const cache = new Map(), products = new Map();
  const scalar = n => {
    if (n[0] === 'name') return Object.hasOwn(inputs, n[1]) && !Array.isArray(inputs[n[1]]);
    if (['grow', 'lag', 'delta'].includes(n[0])) return false;
    return n.slice(1).filter(Array.isArray).every(scalar);
  };
  function at(n, t) {
    if (!cache.has(n)) cache.set(n, new Map());
    const memo = cache.get(n);
    if (memo.has(t)) return memo.get(t);
    const [op, a, b, c] = n;
    let v;
    if (op === 'constant') v = a;
    else if (op === 'name') v = Object.hasOwn(inputs, a) ? (Array.isArray(inputs[a]) ? inputs[a][t] : inputs[a]) : at(data.expressions[a], t);
    else if (op === 'neg') v = -at(a, t);
    else if (op === 'lag' || op === 'delta') {
      if (!scalar(b)) throw Error(op + ' seed must be scalar');
      const previous = t ? at(a, t - 1) : at(b, 0);
      v = op === 'lag' ? previous : at(a, t) - previous;
    } else if (op === 'grow') {
      if (!scalar(a)) throw Error('grow seed must be scalar');
      if (!products.has(n)) products.set(n, new Map());
      const p = products.get(n);
      if (t && !p.has(t - 1)) at(n, t - 1);
      const product = (t ? p.get(t - 1) : 1) * (1 + at(b, t));
      p.set(t, product); v = at(a, 0) * product;
    } else {
      const x = at(a, t), y = b ? at(b, t) : undefined;
      switch (op) {
        case 'Add': v = x + y; break;
        case 'Sub': v = x - y; break;
        case 'Mult': v = x * y; break;
        case 'Div': v = x / y; break;
        case 'abs': v = Math.abs(x); break;
        case 'minimum': v = Math.min(x, y); break;
        case 'maximum': v = Math.max(x, y); break;
        case 'clip': v = Math.min(Math.max(x, y), at(c, t)); break;
        case 'Lt': return x < y;
        case 'LtE': return x <= y;
        case 'Gt': return x > y;
        case 'GtE': return x >= y;
        case 'Eq': return x === y;
        case 'NotEq': return x !== y;
        default: throw Error('Unsupported operation: ' + op);
      }
    }
    memo.set(t, finite(v)); return v;
  }
  const lines = Object.fromEntries(data.order.map(k => [k, []]));
  data.years.forEach((year, t) => {
    for (const key of data.order) lines[key].push(at(data.expressions[key], t));
    for (const check of data.checks) if (!at(check.expression, t)) throw Error('Model check failed in ' + year + ': ' + check.source);
  });
  const series = x => Array.isArray(x) ? x : data.years.map(() => x);
  for (const [key, ref] of Object.entries(data.valuation_refs || {})) {
    valuation[key] = Object.hasOwn(inputs, ref) ? inputs[ref] : lines[ref];
  }
  const rates = series(valuation.wacc), growth = series(valuation.terminal_growth ?? 0).at(-1);
  const shares = series(valuation.shares)[0], cash = series(valuation.net_cash ?? 0)[0];
  if (!(shares > 0)) throw Error('Shares must be positive.');
  if (!rates.every(x => x > -1)) throw Error('Discount rates must exceed −100%.');
  if (!(rates.at(-1) > growth && growth > -1)) throw Error('Final discount rate must exceed terminal growth; growth must exceed −100%.');
  let discount = 1, present = 0;
  lines[data.fcf].forEach((fcf, t) => { discount *= 1 + rates[t]; present += fcf / discount; });
  const terminalPV = lines[data.fcf].at(-1) * (1 + growth) / (rates.at(-1) - growth) / discount;
  const ev = finite(present + terminalPV), equity = finite(ev + cash);
  return {lines, value: {ok: true, ev, equity, per_share: finite(equity / shares), terminal_weight: ev ? finite(terminalPV / ev) : 0}};
}

function dashboardPatch(data, overrides) {
  const {inputs, valuation} = dashboardInputs(data, overrides), patch = {};
  for (const [section, original, changed] of [['bindings', data.inputs, inputs], ['valuation', data.valuation, valuation]]) {
    for (const [key, value] of Object.entries(changed)) {
      const before = original[key];
      const same = Array.isArray(value) ? value.every((v,i) => v === before[i]) : value === before;
      if (!same) (patch[section] ||= {})[key] = value;
    }
  }
  return patch;
}
