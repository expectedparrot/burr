'use strict';
const data = JSON.parse(document.getElementById('dashboard-data').textContent);
const $ = id => document.getElementById(id);
const controls = structuredClone(data.controls), overrides = {};
const invalidFields = new Set();
const fmt = x => x.toLocaleString(undefined, {maximumFractionDigits: 2});
const ratio = c => ['ratio', 'per_period_ratio'].includes(c.unit);
const scale = c => ratio(c) ? 100 : 1;
const modeNames = {shift:'Raise / lower every year',level:'Same value every year',target:'Gradually reach a target'};
const label = c => c.name.replaceAll('_', ' ') + (c.year ? ' · ' + c.year : '') + (ratio(c) ? (c.transform === 'shift' ? ' (percentage points)' : ' (%)') : '');
const sameAssumption = (a,b) => a.section === b.section && a.name === b.name;
for (const c of controls) if (c.enabled && c.transform === 'level') overrides[c.key] = c.base;
function activate(c) {
  for (const other of controls) if (sameAssumption(c,other) && (c.profile || other.profile)) {
    other.enabled = false; delete overrides[other.key]; invalidFields.delete(other.key);
  }
  c.enabled = true;
  if (c.transform === 'level') overrides[c.key] = c.base;
  invalidFields.clear(); renderControls(); recalculate();
} 
const make = (tag, text, parent) => {const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (parent) parent.append(e); return e;};
let current = null, entries = [];
const storageKey = 'burr-dashboard-1:' + data.fingerprint;
try {
  const stored = JSON.parse(localStorage.getItem(storageKey) || '[]');
  if (!Array.isArray(stored) || !stored.every(e => e && e.fingerprint === data.fingerprint && typeof e.note === 'string' && typeof e.timestamp === 'string' && e.overrides && e.results)) throw Error('Invalid stored log');
  entries = stored;
  $('storage-status').textContent = 'Saved locally in this browser. Download the log before clearing browser data.';
} catch (_) { $('storage-status').textContent = 'Browser storage is unavailable or unreadable. New entries last for this session; download the log to keep them.'; }
$('context').textContent = 'Starting scenario: ' + data.scenario + ' · Forecast ' + data.years[0] + '–' + data.years.at(-1) + ' · All calculations run offline.';
$('locked').textContent = 'Reported base-year inputs are held fixed: ' + (data.locked.join(', ') || 'none linked by the model') + '. Shared world inputs are also held fixed.';
$('provenance').textContent = 'Model fingerprint: ' + data.fingerprint + '. Valuation uses burr’s period-by-period DCF convention. Value per share is expressed in the model’s currency/share units. Browser experiments do not update the workspace journal; downloaded choices can be reviewed with burr try and recorded with burr record.';
for (const key of data.order) { const o = make('option', key.replaceAll('_', ' '), $('metric')); o.value = key; }
$('metric').value = Object.hasOwn(data.expressions, 'revenue') ? 'revenue' : data.fcf;

function renderControls() {
  $('parameter').replaceChildren(); $('controls').replaceChildren();
  for (const c of controls) {
    if (!c.enabled) {
      const visible = (!c.profile || c.transform === 'shift') && (c.year === null || $('advanced-years').checked);
      if (visible && !controls.some(other => other.enabled && other.profile && sameAssumption(c,other) && c.profile)) {
        const o = make('option', c.profile ? c.name.replaceAll('_',' ') + ' · whole forecast' : label(c), $('parameter')); o.value = c.key;
      }
      continue;
    }
    const box = make('div', undefined, $('controls')); box.className = 'control';
    const id = 'slider-' + c.key;
    const l = make('label', label(c), box); l.htmlFor = id;
    if (c.profile) {
      const modeLabel = make('label','How should it change?',box), mode = make('select',undefined,box);
      mode.id = id + '-mode'; modeLabel.htmlFor = mode.id;
      for (const candidate of controls.filter(other=>other.profile && sameAssumption(c,other))) {
        const option=make('option',modeNames[candidate.transform],mode);option.value=candidate.key;
      }
      mode.value=c.key; mode.onchange=()=>activate(controls.find(other=>other.key===mode.value));
      const description = c.transform === 'shift'
        ? 'Adds the chosen change to every forecast year, preserving the saved pattern. Zero keeps the saved forecast.'
        : c.transform === 'level' ? 'Uses the selected value in every forecast year.'
        : 'Phases in the change from the saved forecast: the first year stays fixed and the last reaches your target.';
      make('p',description,box).className='muted';
    }
    const slider = make('input', undefined, box); slider.type = 'range'; slider.id = id;
    slider.min = c.min; slider.max = c.max; slider.step = c.step; slider.value = overrides[c.key] ?? c.base;
    const numberLabel = make('label', 'Value', box);
    const number = make('input', undefined, numberLabel); number.type = 'number'; number.step = 'any';
    number.min = c.min * scale(c); number.max = c.max * scale(c); number.value = Number(((overrides[c.key] ?? c.base) * scale(c)).toPrecision(12));
    const update = value => {
      if (!Number.isFinite(value) || value < c.min || value > c.max) { invalidFields.add(c.key); invalid('Enter a value within the slider range.'); return; }
      invalidFields.delete(c.key);
      if (value === c.base && c.transform !== 'level') delete overrides[c.key]; else overrides[c.key] = value;
      slider.value = value; number.value = Number((value * scale(c)).toPrecision(12)); recalculate();
    };
    slider.addEventListener('input', () => update(slider.valueAsNumber));
    number.addEventListener('input', () => update(number.valueAsNumber / scale(c)));
    if(c.profile) {
      const pathDetails=make('details',undefined,box);make('summary','Annual assumption values',pathDetails);
      const preview=make('div',undefined,pathDetails);preview.className='scroll';preview.dataset.profileKey=c.key;
    }
    const settings = make('details', undefined, box); make('summary', 'Range and evidence', settings);
    const ranges = make('div', undefined, settings); ranges.className = 'range-settings';
    const fields = {};
    for (const [key, title] of [['min','Minimum'],['max','Maximum'],['step','Step']]) {
      const l = make('label', title, ranges), input = make('input', undefined, l);
      input.type = 'number'; input.step = 'any'; input.value = Number((c[key] * scale(c)).toPrecision(12)); fields[key] = input;
    }
    const rangeError = make('p', '', settings); rangeError.className = 'error'; rangeError.hidden = true;
    const apply = make('button', 'Apply range', settings); apply.className = 'secondary';
    apply.onclick = () => {
      const low = fields.min.valueAsNumber / scale(c), high = fields.max.valueAsNumber / scale(c), step = fields.step.valueAsNumber / scale(c);
      const value = overrides[c.key] ?? c.base;
      if (![low, high, step].every(Number.isFinite) || low >= high || step <= 0 || step > high-low || low > Math.min(value,c.base) || high < Math.max(value,c.base)) {
        rangeError.hidden = false; rangeError.textContent = 'Use a positive step and a range containing the saved and current values.'; return;
      }
      Object.assign(c, {min: low, max: high, step}); renderControls(); recalculate();
    };
    make('p', 'Saved value: ' + fmt(c.base * scale(c)) + (ratio(c) ? '%' : ''), settings);
    for (const [key, value] of Object.entries(c.metadata)) make('p', key + ': ' + value, settings);
    const remove = make('button', 'Return to fixed', box); remove.className = 'secondary';
    remove.onclick = () => { c.enabled = false; delete overrides[c.key]; invalidFields.delete(c.key); renderControls(); recalculate(); };
  }
  $('add').disabled = !$('parameter').options.length;
}
function invalid(message) {
  current = null; $('error').hidden = false; $('error').textContent = message;
  for (const id of ['price','ev','terminal']) $(id).textContent = '—';
  $('delta').textContent = 'Resolve the input error to calculate a value.';
  $('chart').replaceChildren(); $('forecast').replaceChildren(); $('save').disabled = true; $('download-patch').disabled = true;
  for(const preview of document.querySelectorAll('[data-profile-key]')) preview.replaceChildren();
}
function renderProfiles() {
  const resolved = dashboardInputs(data, overrides);
  for(const preview of document.querySelectorAll('[data-profile-key]')) {
    const c=controls.find(c=>c.key===preview.dataset.profileKey);
    const values=c.section==='bindings'?resolved.inputs[c.name]:resolved.valuation[c.name];
    preview.replaceChildren();const table=make('table',undefined,preview),head=make('tr',undefined,make('thead',undefined,table));
    for(const name of ['Year','Saved','Your choices'])make('th',name,head);
    const body=make('tbody',undefined,table);
    data.years.forEach((year,i)=>{const row=make('tr',undefined,body);make('th',year,row);
      for(const value of [c.profile[i],values[i]])make('td',fmt(value*scale(c))+(ratio(c)?'%':''),row);
    });
  }
}
function recalculate() {
  if (invalidFields.size) { invalid('Enter a value within the slider range, or reset the values.'); return; }
  try {
    current = evaluateDashboard(data, overrides); $('error').hidden = true;
    $('price').textContent = fmt(current.value.per_share);
    const gap = current.value.per_share - data.baseline.value.per_share;
    $('delta').textContent = (gap >= 0 ? '+' : '') + fmt(gap) + ' vs saved ' + fmt(data.baseline.value.per_share);
    $('ev').textContent = fmt(current.value.ev); $('terminal').textContent = fmt(current.value.terminal_weight * 100) + '%';
    $('save').disabled = false; $('download-patch').disabled = !Object.keys(dashboardPatch(data, overrides)).length;
    renderProfiles(); renderForecast();
  } catch (error) { invalid(error.message); }
}
function renderForecast() {
  if (!current) return;
  const key = $('metric').value, saved = data.baseline.lines[key], trial = current.lines[key];
  const history = data.history[key], reported = new Map(history.map(row => [row.period, row.value]));
  const firstYear = history.length ? history[0].period : data.years[0], lastYear = data.years.at(-1);
  const years = Array.from({length: lastYear-firstYear+1}, (_, i) => firstYear+i);
  const percentage = ['ratio','per_period_ratio'].includes(data.units[key]);
  const format = v => fmt(percentage ? v * 100 : v) + (percentage ? '%' : '');
  $('history-note').textContent = history.length
    ? 'Reported observations: ' + history[0].period + '–' + history.at(-1).period + '. Forecast begins in ' + data.years[0] + '. Source: ' + data.history_source + '.'
    : 'No matching pre-forecast observations are available for this metric. Forecast begins in ' + data.years[0] + '.';
  const low = Math.min(0,...saved,...trial,...reported.values()), high = Math.max(0,...saved,...trial,...reported.values()), span = high-low || 1;
  const x = year => 80 + (year-firstYear) * 600 / Math.max(1, lastYear-firstYear), y = v => 205 - (v-low)/span*170;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', '0 0 730 250'); svg.setAttribute('role','img'); svg.setAttribute('aria-label', key + ': reported history and saved and trial forecasts');
  function element(tag, attrs, text) {const e = document.createElementNS(ns,tag); for(const [k,v] of Object.entries(attrs)) e.setAttribute(k,v); if(text !== undefined) e.textContent=text; svg.append(e); return e;}
  const boundary = history.length ? x(data.years[0]-.5) : 80;
  element('rect',{x:boundary,y:15,width:710-boundary,height:200,fill:'#eef5ef','data-region':'forecast'});
  if (history.length) element('line',{x1:boundary,x2:boundary,y1:15,y2:215,stroke:'#a4bbae','stroke-dasharray':'3 4','data-boundary':'forecast'});
  element('text',{x:boundary+8,y:28,'font-size':11,fill:'#526b65'},'Forecast');
  element('line',{x1:80,x2:680,y1:y(0),y2:y(0),stroke:'#ccdcd3'});
  element('text',{x:5,y:45,'font-size':11},format(high)); element('text',{x:5,y:210,'font-size':11},format(low));
  const series = [
    {name:'reported',title:'Reported',points:history.map(row=>[row.period,row.value]),color:'#296eaa',dash:''},
    {name:'saved',title:'Saved forecast',points:data.years.map((year,i)=>[year,saved[i]]),color:'#8a9792',dash:'5 5'},
    {name:'trial',title:'Your choices',points:data.years.map((year,i)=>[year,trial[i]]),color:'#12684e',dash:''}
  ];
  for (const {name,title,points,color,dash} of series) {
    // Separate series and missing years never imply an observed transition.
    points.forEach(([year,value],i)=>{
      if(i && year===points[i-1][0]+1) element('line',{x1:x(points[i-1][0]),y1:y(points[i-1][1]),x2:x(year),y2:y(value),stroke:color,'stroke-width':3,'stroke-dasharray':dash,'data-series':name});
      const circle=element('circle',{cx:x(year),cy:y(value),r:4,fill:color,'data-series':name,'data-year':year,'data-value':value});
      const tooltip=document.createElementNS(ns,'title'); tooltip.textContent=title+' · '+year+': '+format(value)+(name==='reported'?' · '+data.history_source:'');circle.append(tooltip);
    });
  }
  const tickEvery = Math.max(1, Math.ceil(years.length/10));
  years.forEach((year,i)=>{if(i%tickEvery===0 || year===lastYear) element('text',{x:x(year),y:235,'text-anchor':'middle','font-size':12},year);});
  $('chart').replaceChildren(svg); $('forecast').replaceChildren();
  const table=make('table',undefined,$('forecast')), head=make('tr',undefined,make('thead',undefined,table));
  for (const title of ['Series',...years]) make('th',title,head);
  const body=make('tbody',undefined,table);
  for(const {title,points} of series) {
    const values = new Map(points), row=make('tr',undefined,body);make('th',title,row);
    years.forEach(year=>make('td',values.has(year)?format(values.get(year)):'—',row));
  }
}
function download(name, value) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)], {type:'application/json'}));
  const a = make('a'); a.href=url; a.download=name; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function renderLog() {
  $('log').replaceChildren();
  for (const e of [...entries].reverse()) {
    const box=make('div',undefined,$('log'));box.className='entry';
    make('strong',e.note || 'Untitled experiment',box);make('p',e.timestamp + ' · Value per share: ' + fmt(e.results.value.per_share),box);
    const details=make('details',undefined,box);make('summary','Assumptions and results',details);make('pre',JSON.stringify(e.patch,null,2),details);
    const restore=make('button','Restore choices',box);restore.className='secondary';restore.onclick=()=>{
      try {evaluateDashboard(data,e.overrides);} catch(error) {invalid(error.message);return;}
      for(const k of Object.keys(overrides)) delete overrides[k];Object.assign(overrides,e.overrides);invalidFields.clear();
      for(const c of controls) {
        const saved = (e.sliders || []).find(s => s.key === c.key);
        c.enabled = Boolean(saved) || Object.hasOwn(overrides,c.key);
        if(saved && [saved.min,saved.max,saved.step].every(Number.isFinite) && saved.min < saved.max && saved.step > 0) Object.assign(c,{min:saved.min,max:saved.max,step:saved.step});
        c.min=Math.min(c.min,c.base,overrides[c.key] ?? c.base);c.max=Math.max(c.max,c.base,overrides[c.key] ?? c.base);
      }
      renderControls();recalculate();
    };
  }
}
$('add').onclick=()=>{const c=controls.find(c=>c.key===$('parameter').value);if(c)activate(c);};
$('advanced-years').onchange=()=>{invalidFields.clear();renderControls();recalculate();};
$('reset').onclick=()=>{
  for(const k of Object.keys(overrides)) delete overrides[k];
  for(const c of controls) if(c.enabled && c.profile && c.transform!=='shift') {
    c.enabled=false;controls.find(other=>sameAssumption(c,other)&&other.transform==='shift').enabled=true;
  }
  invalidFields.clear();renderControls();recalculate();
};
$('metric').onchange=renderForecast;
$('save').onclick=()=>{
  if(!current)return;
  const entry={id:crypto.randomUUID ? crypto.randomUUID() : String(Date.now())+'-'+entries.length,timestamp:new Date().toISOString(),entity:data.entity,scenario:data.scenario,fingerprint:data.fingerprint,note:$('note').value,overrides:structuredClone(overrides),patch:dashboardPatch(data,overrides),results:structuredClone(current),baseline:data.baseline.value,sliders:controls.filter(c=>c.enabled).map(({key,min,max,step,transform})=>({key,min,max,step,transform}))};
  entries.push(entry);
  try{localStorage.setItem(storageKey,JSON.stringify(entries));$('storage-status').textContent='Experiment saved in this browser. Download the log to share or keep a copy.';}
  catch(_){$('storage-status').textContent='Experiment saved for this session only. Browser storage is unavailable or full; download the log to keep it.';}
  $('note').value='';renderLog();
};
$('download-log').onclick=()=>download(data.entity+'-experiments.json',{schema:data.schema,fingerprint:data.fingerprint,entity:data.entity,scenario:data.scenario,entries});
$('download-patch').onclick=()=>{if(current)download(data.entity+'-choices.json',dashboardPatch(data,overrides));};
renderControls();renderLog();recalculate();
