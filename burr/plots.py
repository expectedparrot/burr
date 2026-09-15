"""Deterministic, offline SVG/HTML views of model outputs and evidence.

No valuation is computed by these views. Every plotted observation retains its
period, scenario, source, and raw value; units are never combined across panels.
"""

from html import escape
from pathlib import Path
import math
import textwrap

from .errors import require
from .operations import graph
from .storage import atomic_write, json_text


COLORS = ("#187452", "#b45428", "#3c65ab", "#8652a1", "#987315", "#317e88")
UNIT_LABELS = {"currency_m": "Currency (millions)", "currency": "Currency",
               "count": "Count", "ratio": "Percent", "per_period_ratio": "Percent per period"}


def label(name):
    words = name.replace("_", " ").capitalize().split()
    return ' '.join(word.upper() if word.lower() in {"gsv", "ebitda", "ebit", "fcff", "fcf", "sbc", "nwc", "gaap"}
                    else word for word in words)


def formatted(value, unit=None):
    if unit in {"ratio", "per_period_ratio"}:
        return f"{value * 100:,.3g}%"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if value and abs(value) < .001:
        return f"{value:.3g}"
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def axis_bounds(values):
    low, high = min(0.0, min(values)), max(0.0, max(values))
    if low == high:
        return -1.0, 1.0, .5
    span = high - low
    require(math.isfinite(span), "eval_error", "plot values exceed supported numeric range")
    target = span / 5
    require(target > 0, "eval_error", "plot values are too small to scale")
    magnitude = 10 ** math.floor(math.log10(target))
    step = next(factor * magnitude for factor in (1, 2, 2.5, 5, 10) if factor * magnitude >= target)
    low = math.floor((low - span * .05 if low < 0 else 0) / step) * step
    high = math.ceil((high + span * .08 if high > 0 else 0) / step) * step
    require(math.isfinite(high - low), "eval_error", "plot values exceed supported numeric range")
    return low, high, step


def plot_data(workspace, *, kind, lines, scenario="base", all_scenarios=False,
              actuals_only=False, period=None, title=None, note=""):
    require(kind in {"series", "scenarios", "drivers"}, "usage_error", "unknown plot kind", exit_code=2)
    names = list(dict.fromkeys(name.strip() for name in lines.split(",") if name.strip()))
    require(names and len(names) <= 24, "usage_error", "choose between 1 and 24 lines", exit_code=2)
    require(not (actuals_only or all_scenarios) or kind == "series", "usage_error",
            "--actuals-only and --all-scenarios apply only to series plots", exit_code=2)
    require(not (actuals_only and all_scenarios), "usage_error",
            "choose --actuals-only or --all-scenarios", exit_code=2)
    require(period is None or kind != "series", "usage_error",
            "--period applies to scenario and driver plots", exit_code=2)
    require(kind != "drivers" or len(names) == 1, "usage_error",
            "driver diagrams require exactly one line", exit_code=2)
    model = workspace.model(scenario)
    selected = ["base", *workspace.scenarios()] if all_scenarios or kind == "scenarios" else [scenario]
    models = {name: workspace.model(name) for name in selected}
    for candidate in models.values():
        candidate.run()
    actual_names = {row["line"] for row in workspace.actuals}
    available = actual_names if actuals_only else set(model.template["lines"])
    require(set(names) <= available, "unknown_name",
            f"unknown plot lines: {', '.join(sorted(set(names) - available))}",
            hint="use run or export to inspect available lines; extra actuals require --actuals-only")
    year = model.years[-1] if period is None else period
    require(kind == "series" or all(year in m.years for m in models.values()), "usage_error",
            "plot period must belong to the forecast horizon", exit_code=2)
    result = {"ok": True, "kind": kind, "entity": model.entity,
              "title": title or f"{label(model.entity)} · {label(kind)}",
              "note": note, "panels": [],
              "fingerprints": {name: workspace.fingerprint(name) for name in selected},
              "scenario_theses": {name: patch["thesis"] for name, patch in workspace.scenarios().items()
                                  if name in selected and not actuals_only}}
    source = workspace.relative(workspace.company / "actuals.csv")
    if kind == "drivers":
        full = graph(model, formulas=True)
        retained, pending = set(), [names[0]]
        while pending:
            node = pending.pop()
            if node in retained:
                continue
            retained.add(node)
            pending.extend(edge["from"] for edge in full["edges"] if edge["to"] == node)
        from .values import series
        results = model.run()
        nodes = []
        for node in full["nodes"]:
            name = node["id"]
            if name not in retained:
                continue
            values = results[name] if name in results else series(model.inputs[name], len(model.years))
            form = model.params["bindings"].get(name, workspace.world.get(name, {}))
            nodes.append({**node, "value": values[model.years.index(year)], "unit": model.units.get(name),
                          "metadata": form if node["kind"] == "binding" else {},
                          "provenance": (model.template_file + ":lines." + name if name in results else
                                         (model.file + ":bindings." if name in model.params["bindings"] else "world.yaml:") + name)})
        result["panels"].append({"line": names[0], "scenario": scenario, "period": year, "nodes": nodes,
                                 "edges": [edge for edge in full["edges"]
                                           if edge["from"] in retained and edge["to"] in retained]})
        return result
    for name in names:
        rows = []
        if kind == "series":
            rows.extend({**row, "scenario": "actuals", "kind": "reported", "provenance": source}
                        for row in workspace.actuals if row["line"] == name)
        if not actuals_only:
            for candidate in models.values():
                rows.extend({**row, "kind": "forecast"} for row in candidate.rows()
                            if row["line"] == name and (kind == "series" or row["period"] == year))
        require(rows, "eval_error", f"no observations to plot for {name}")
        result["panels"].append({"line": name, "unit": model.units.get(name), "rows": rows})
    return result


def text(x, y, value, *, size=13, fill="#244139", anchor="start", extra=""):
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" {extra}>{escape(str(value))}</text>')


def line(x1, y1, x2, y2, *, stroke="#dce5df", extra=""):
    return (f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{stroke}" {extra}/>')


def rect(x, y, w, h, fill, *, extra=""):
    return (f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
            f'fill="{fill}" {extra}/>')


def group_rows(panel):
    def key(row):
        return "reported" if row["kind"] == "reported" else "forecast:" + row["scenario"]
    names = list(dict.fromkeys(key(row) for row in panel["rows"]))
    return [(name, [row for row in panel["rows"] if key(row) == name]) for name in names]


def series_label(name):
    return "Reported" if name == "reported" else name.removeprefix("forecast:") + " forecast"


def series_style(name, index):
    return "#52665c" if name == "reported" else COLORS[index % len(COLORS)]


def cartesian(panel, kind):
    width, height = 940, 430
    left, right, top, bottom = 104, 910, 85, 338
    rows, unit = panel["rows"], panel["unit"]
    groups = group_rows(panel)
    low, high, tick_step = axis_bounds([row["value"] for row in rows])
    y = lambda value: bottom - (value - low) / (high - low) * (bottom - top)
    out = [text(24, 30, label(panel["line"]), size=21),
           text(24, 54, UNIT_LABELS.get(unit, "Unit unspecified"), size=12, fill="#617568")]
    if kind == "series":
        years = sorted({row["period"] for row in rows})
        first, last = years[0] - .3, years[-1] + .3
        x = lambda year: left + (year - first) / (last - first) * (right - left)
        forecasts = [row["period"] for row in rows if row["kind"] == "forecast"]
        if forecasts:
            start = max(left, x(min(forecasts) - .5))
            out += [rect(start, top, right - start, bottom - top, "#f0f6ef"),
                    text(right, top - 10, "Shaded: modeled forecast", size=11, anchor="end")]
        stride = max(1, (len(years) + 11) // 12)
        ticks = sorted(set(years[::stride] + [years[-1]]))
        out.extend(text(x(year), bottom + 24, year, size=12, anchor="middle") for year in ticks)
    for i in range(round((high - low) / tick_step) + 1):
        value = low + tick_step * i
        out += [line(left, y(value), right, y(value)),
                text(left - 12, y(value) + 4, formatted(value, unit), anchor="end", size=12)]
    out.append(line(left, y(0), right, y(0), stroke="#8a9e90"))
    if kind == "scenarios":
        step = (right - left) / len(rows)
        for i, row in enumerate(rows):
            cx, value = left + (i + .5) * step, row["value"]
            color = COLORS[i % len(COLORS)]
            tooltip = escape(f'{row["scenario"]}, {row["period"]}: {value:.12g}; {row["provenance"]}')
            bar = rect(cx - step * .3, min(y(value), y(0)), step * .6, abs(y(value) - y(0)), color)
            out += [f'<g>{bar}<title>{tooltip}</title></g>',
                    text(cx, y(value) - 7 if value >= 0 else y(value) + 18, formatted(value, unit), anchor="middle"),
                    text(cx, bottom + 24, row["scenario"], size=12, anchor="middle")]
        out.append(text(left, 399, f'Forecast period: {rows[0]["period"]} · Bars start at zero.', size=12))
    else:
        legend_y = 386
        for i, (name, observations) in enumerate(groups):
            color = series_style(name, i - (groups[0][0] == "reported"))
            dash = '' if name == "reported" else 'stroke-dasharray="7 4"'
            out.append(f'<g data-series="{escape(name, quote=True)}">')
            observations = sorted(observations, key=lambda row: row["period"])
            for previous, current in zip(observations, observations[1:]):
                # Missing years and the actual/forecast boundary are never bridged.
                if current["period"] == previous["period"] + 1:
                    out.append(line(x(previous["period"]), y(previous["value"]), x(current["period"]),
                                    y(current["value"]), stroke=color, extra=f'stroke-width="2.5" {dash}'))
            for row in observations:
                tooltip = escape(f'{series_label(name)}, {row["period"]}: {row["value"]:.12g}; {row["provenance"]}')
                out.append(f'<circle cx="{x(row["period"]):.2f}" cy="{y(row["value"]):.2f}" '
                           f'r="4" fill="{color}"><title>{tooltip}</title></circle>')
            out.append('</g>')
            lx, ly = left + (i % 4) * 196, legend_y + (i // 4) * 24
            out += [line(lx, ly - 4, lx + 22, ly - 4, stroke=color, extra=f'stroke-width="3" {dash}'),
                    text(lx + 30, ly, series_label(name), size=12)]
        height += max(0, (len(groups) - 1) // 4) * 24
    return "\n".join(out), width, height


def drivers(panel):
    nodes, edges = panel["nodes"], panel["edges"]
    ranks, pending = {}, {node["id"] for node in nodes}
    while pending:
        ready = sorted(name for name in pending if all(edge["from"] in ranks for edge in edges
                                                       if edge["to"] == name and not edge["lagged"]))
        require(ready, "circular_dependency", "cannot lay out non-lagged model dependencies")
        for name in ready:
            ranks[name] = max((ranks[edge["from"]] + 1 for edge in edges
                               if edge["to"] == name and not edge["lagged"]), default=0)
            pending.remove(name)
    columns = [[node for node in nodes if ranks[node["id"]] == rank] for rank in range(max(ranks.values()) + 1)]
    cell = max(290, max(len(node["id"]) for node in nodes) * 8 + 32)
    width, height = len(columns) * (cell + 65) + 30, max(map(len, columns)) * 118 + 140
    positions = {node["id"]: (24 + col * (cell + 65), 105 + (max(map(len, columns)) - len(column)) * 59 + row * 118)
                 for col, column in enumerate(columns) for row, node in enumerate(column)}
    out = [text(24, 30, f'{label(panel["line"])} · model drivers', size=21),
           text(24, 56, f'{panel["scenario"]} · {panel["period"]} · Filled boxes: inputs; white boxes: formulas. Dashed arrows: prior period.', size=12),
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#8a9e90"/></marker></defs>']
    for edge in edges:
        sx, sy = positions[edge["from"]]
        tx, ty = positions[edge["to"]]
        dash = ' stroke-dasharray="6 4"' if edge["lagged"] else ''
        if tx <= sx:
            path = f'M {sx + cell} {sy + 36} C {sx + cell + 30} {sy - 40}, {tx - 30} {ty - 40}, {tx} {ty + 36}'
        else:
            middle = (sx + cell + tx) / 2
            path = f'M {sx + cell} {sy + 36} C {middle} {sy + 36}, {middle} {ty + 36}, {tx} {ty + 36}'
        out.append(f'<path d="{path}" fill="none" stroke="#8a9e90"{dash} marker-end="url(#arrow)"><title>{escape(edge["from"] + " → " + edge["to"] + (" (prior period)" if edge["lagged"] else ""))}</title></path>')
    for node in nodes:
        x, y = positions[node["id"]]
        tooltip = node.get("formula") or json_text(node["metadata"]).strip()
        out.extend(['<g>', f'<title>{escape(tooltip)}</title>',
                    rect(x, y, cell, 76, "#e8f2e8" if node["kind"] == "binding" else "white", extra='rx="7" stroke="#a6bcae"'),
                    text(x + 12, y + 26, node["id"], size=14),
                    text(x + 12, y + 53, f'{formatted(node["value"], node["unit"])} · {UNIT_LABELS.get(node["unit"], "Unit unspecified")}', size=12), '</g>'])
    return "\n".join(out), width, height


def svg(content, width, height, title, metadata=None):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}" role="img" aria-label="{escape(title, quote=True)}" '
            'style="font-family:system-ui,sans-serif;background:white">'
            f'<title>{escape(title)}</title>'
            + (f'<metadata>{escape(json_text(metadata))}</metadata>' if metadata is not None else '')
            + content + '</svg>')


def data_table(panel):
    rows = panel.get("rows", panel.get("nodes", []))
    columns = (["period", "scenario", "kind", "value", "provenance"] if "rows" in panel else
               ["id", "kind", "value", "unit", "formula", "metadata", "provenance"])
    header = ''.join(f'<th scope="col">{escape(label(name))}</th>' for name in columns)
    body = ''.join('<tr>' + ''.join(f'<td>{escape(json_text(row.get(name, "")).strip() if isinstance(row.get(name), dict) else str(row.get(name, "")))}</td>'
                                   for name in columns) + '</tr>' for row in rows)
    return f'<details><summary>Inspect data and provenance</summary><div class="scroll"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div></details>'


STYLE = """
*{box-sizing:border-box}body{margin:0;color:#244139;background:#f3f6f1;font:15px/1.6 system-ui,sans-serif}
main{max-width:1160px;margin:auto;padding:38px 24px}h1{font:38px Georgia,serif;margin:0 0 14px}p{max-width:85ch}
.eyebrow{text-transform:uppercase;letter-spacing:.15em;font-size:12px}.muted{color:#607568;font-size:13px}
section{margin:25px 0;background:white;padding:20px;border:1px solid #dbe5db;border-radius:10px}
.scroll{overflow:auto}svg{display:block;width:100%;height:auto;min-width:640px}
button,summary,label{cursor:pointer}button{background:#1b694c;border:0;color:white;padding:9px 14px;border-radius:5px;font:inherit}
button.secondary{background:#edf3ec;color:#244139}button:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid #b45428;outline-offset:3px}
.controls{display:flex;flex-wrap:wrap;gap:16px;align-items:center;margin-bottom:12px}label{font-size:13px}input{accent-color:#187452}
details{margin-top:18px}summary{font-size:13px;color:#187452}td,th{text-align:left;padding:9px;border-bottom:1px solid #dce5df;font-size:12px}
td{overflow-wrap:anywhere;min-width:80px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th{white-space:nowrap}
footer{font-size:12px;color:#607568;overflow-wrap:anywhere;border-top:1px solid #dce5df;padding-top:18px}a{color:#187452}
@media(max-width:700px){main{padding:22px 12px}section{padding:12px}h1{font-size:30px}}
@media print{@page{size:landscape;margin:12mm}body{background:white}main{padding:0;max-width:none}button,.controls,details{display:none}section{break-inside:avoid;border:0;padding:0}.scroll{overflow:visible}svg,.drivers svg{width:100%;min-width:0;height:auto}footer{font-size:9px}}
"""


SCRIPT = """
function download(content,type,name){const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
document.querySelectorAll('input[data-series]').forEach(input=>input.addEventListener('change',()=>{input.closest('section').querySelectorAll('g[data-series]').forEach(group=>{if(group.dataset.series===input.dataset.series)group.style.display=input.checked?'':'none';});}));
document.querySelectorAll('button[data-svg]').forEach(button=>button.addEventListener('click',()=>{const svg=button.closest('section').querySelector('svg').cloneNode(true);svg.querySelectorAll('g[data-series]').forEach(group=>group.style.removeProperty('display'));download(new XMLSerializer().serializeToString(svg),'image/svg+xml',button.dataset.svg);}));
document.getElementById('data-download').addEventListener('click',()=>download(document.getElementById('plot-data').textContent,'application/json','burr-plot-data.json'));
document.getElementById('print').addEventListener('click',()=>window.print());
"""


def render(data, extension):
    panels = [drivers(panel) if data["kind"] == "drivers" else cartesian(panel, data["kind"])
              for panel in data["panels"]]
    notice = ("Reported observations and modeled forecasts are separate series. Forecasts reflect assumptions. "
              "Matching line names do not establish identical metric definitions; check comparability. "
              "Ratios display as percentages; downloadable data retains raw values.")
    if data["kind"] == "drivers":
        notice = ("Arrows show formula dependencies. Values use the selected scenario and period. "
                  "Hover over a node or inspect the data table to read its formula or input metadata. "
                  "This diagram represents model logic, not evidence of causation.")
    elif data["kind"] == "scenarios":
        notice = ("Each panel compares modeled outcomes for one metric at the selected forecast date. "
                  "Panels have separate axes and units. Scenario theses are included below the charts.")
    if extension == ".svg":
        width = max(width for _, width, _ in panels)
        content = [text(24, 35, data["title"], size=25)]
        y = 64
        for paragraph in [data["note"], notice]:
            for row in textwrap.wrap(paragraph, max(60, int((width - 48) / 7))):
                content.append(text(24, y, row, size=12)); y += 20
        for inner, _, height in panels:
            content.append(f'<g transform="translate(0,{y})">{inner}</g>'); y += height + 20
        content.append(text(24, y, "burr · Static model snapshot · Raw data and fingerprints embedded in SVG metadata", size=12))
        return svg(''.join(content), width, y + 25, data["title"], data)
    sections = []
    for panel, (inner, width, height) in zip(data["panels"], panels):
        controls = ''
        if data["kind"] == "series":
            controls = ''.join(f'<label><input type="checkbox" checked data-series="{escape(name, quote=True)}"> {escape(series_label(name))}</label>'
                               for name, _ in group_rows(panel))
        filename = escape(f'{data["entity"]}-{panel["line"]}-{data["kind"]}.svg', quote=True)
        visual = svg(inner, width, height, label(panel["line"]), {**data, "panels": [panel]})
        sections.append(f'<section aria-label="{escape(label(panel["line"]), quote=True)}"><div class="controls">{controls}'
                        f'<button class="secondary" data-svg="{filename}">Download SVG (all series)</button></div>'
                        f'<div class="scroll {data["kind"]}" tabindex="0">{visual}</div>{data_table(panel)}</section>')
    encoded = json_text(data).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    theses = ''.join(f'<li><strong>{escape(name)}:</strong> {escape(thesis)}</li>' for name, thesis in data["scenario_theses"].items())
    fingerprints = ' · '.join(f'{name}: {value}' for name, value in data["fingerprints"].items())
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(data["title"])}</title><style>{STYLE}</style></head><body><main>'
            f'<p class="eyebrow">burr · {escape(data["entity"])}</p><h1>{escape(data["title"])}</h1>'
            f'<p>{escape(data["note"])}</p><p class="muted">{notice}</p>'
            '<div class="controls"><button id="data-download">Download chart data</button><button id="print" class="secondary">Print / Save PDF</button></div>'
            + ''.join(sections) + (f'<details><summary>Scenario theses</summary><ul>{theses}</ul></details>' if theses else '')
            + f'<footer><p>Static snapshot; regenerate after model changes. No network connection is needed to view this file.</p><p>Workspace fingerprints · {escape(fingerprints)}</p></footer>'
            f'<script type="application/json" id="plot-data">{encoded}</script><script>{SCRIPT}</script></main></body></html>\n')


def emit_plot(workspace, path, **options):
    path = Path(path)
    require(path.suffix.lower() in {".html", ".svg"}, "usage_error",
            "plot output must end in .html or .svg", exit_code=2)
    data = plot_data(workspace, **options)
    atomic_write(path, render(data, path.suffix.lower()))
    return {**data, "output": str(path)}
