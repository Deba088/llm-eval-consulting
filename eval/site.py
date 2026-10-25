"""Build a static results website (docs/index.html) from the saved eval results, for GitHub Pages.

The page has a model leaderboard, scores per dimension, judge comparison and agreement, case x model heatmaps
and a filterable table of every judgement. All data is embedded in the one HTML file; charts use Chart.js
from a CDN. Re-run after every eval to refresh the page, then commit docs/ and push.

GitHub Pages sites are public, so the page never contains any dataset content: no case names, case text,
questions, golden answers, model answers, judge reasoning or key-point text. Cases appear only by their ID
(e.g. q001) and difficulty; everything else is numbers (scores, counts, words, latency, cost).

Usage (from the project root):
    python -m eval.site                        # -> docs/index.html
    python -m eval.site --out site/index.html  # write somewhere else
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import yaml

from . import ROOT
from .llm import DIMENSIONS
from .results import JsonlStore, is_current
from .run_eval import DEFAULT_CONFIG, load_items

DIMENSION_LABELS = {
    "coverage": "Coverage",
    "mece": "MECE",
    "client_specificity": "Client specificity",
    "depth_and_insight": "Depth & insight",
    "prioritisation_and_flow": "Prioritisation",
    "instruction_following": "Instruction following",
}


def build_data(cfg):
    """Collect the numbers the page needs, using the same rules as the Excel report. No dataset text is included."""
    items = load_items(ROOT / cfg["dataset"])
    items_by_key = {f"{i['case_id']}|{i['question_key']}": i for i in items}
    out_dir = ROOT / cfg["output_dir"]
    answers = JsonlStore(out_dir / "answers.jsonl").records
    judgements = JsonlStore(out_dir / "judgements.jsonl").records
    judges = [spec["id"] for spec in cfg["judges"]["models"]]
    config_models = [spec["id"] for spec in cfg["candidates"]["models"]]

    answers = {k: a for k, a in answers.items() if f"{a['case_id']}|{a['question_key']}" in items_by_key}
    judged = [j for j in judgements.values()
              if j["judge"] in judges and j["answer_key"] in answers and is_current(j, answers)]
    evaluated = {a["model"] for a in answers.values()}
    models = [m for m in config_models if m in evaluated] + sorted(evaluated - set(config_models))

    data_answers = []
    for key, a in sorted(answers.items()):
        data_answers.append({"key": key, "item": f"{a['case_id']}|{a['question_key']}", "model": a["model"],
                             "run": a["run"], "words": a.get("words"), "latency": a.get("latency_s"),
                             "cost": a.get("cost_usd"), "promptTokens": a.get("prompt_tokens"),
                             "completionTokens": a.get("completion_tokens")})

    data_judgements = []
    for j in sorted(judged, key=lambda j: j["key"]):
        data = j["judgement"]
        kp = data.get("key_points") or []
        data_judgements.append({
            "answer": j["answer_key"], "judge": j["judge"], "cost": j.get("cost_usd"),
            "scores": [data["scores"][d]["score"] for d in DIMENSIONS],
            "keyPoints": {c: sum(1 for p in kp if p.get("covered") == c) for c in ("full", "partial", "none")},
        })

    used_items = {a["item"] for a in data_answers}
    return {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dimensions": [{"id": d, "label": DIMENSION_LABELS.get(d, d)} for d in DIMENSIONS],
        "models": models,
        "judges": judges,
        "items": [{"key": k, "caseId": i["case_id"], "difficulty": i["difficulty"], "question": i["question_key"]}
                  for k, i in items_by_key.items() if k in used_items],
        "answers": data_answers,
        "judgements": data_judgements,
    }


def render(data, title):
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return PAGE.replace("__TITLE__", title).replace("__DATA__", payload)


def main():
    parser = argparse.ArgumentParser(prog="python -m eval.site", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="settings file (default eval/config.yaml)")
    parser.add_argument("--out", default=ROOT / "docs" / "index.html", help="output file (default docs/index.html)")
    parser.add_argument("--title", default="LLM Eval: Consulting Case Structuring", help="page title")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    data = build_data(cfg)
    if not data["judgements"]:
        print("Note: no judgements found yet; the page will be empty. Run python -m eval.run_eval first.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data, args.title), encoding="utf-8")
    (out.parent / ".nojekyll").touch()  # serve the file as-is on GitHub Pages
    print(f"Saved {out} ({len(data['models'])} models, {len(data['items'])} questions, "
          f"{len(data['answers'])} answers, {len(data['judgements'])} judgements; no dataset text)")


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #F6F4EF; --surface: #FFFFFF; --ink: #14213D; --muted: #5B6680; --line: #E2DED5;
    --accent: #0F766E; --accent-rgb: 15,118,110; --warn: #B45309; --warn-rgb: 180,83,9;
    --series-1: #0F766E; --series-2: #2563EB; --series-3: #B45309; --series-4: #7C3AED;
    --series-5: #DB2777; --series-6: #4D7C0F;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0F1424; --surface: #171E33; --ink: #E7EBF3; --muted: #9AA5BD; --line: #2A3350;
      --accent: #2DD4BF; --accent-rgb: 45,212,191; --warn: #F59E0B; --warn-rgb: 245,158,11;
      --series-1: #2DD4BF; --series-2: #60A5FA; --series-3: #F59E0B; --series-4: #A78BFA;
      --series-5: #F472B6; --series-6: #A3E635;
    }
  }
  :root[data-theme="dark"] {
    --bg: #0F1424; --surface: #171E33; --ink: #E7EBF3; --muted: #9AA5BD; --line: #2A3350;
    --accent: #2DD4BF; --accent-rgb: 45,212,191; --warn: #F59E0B; --warn-rgb: 245,158,11;
    --series-1: #2DD4BF; --series-2: #60A5FA; --series-3: #F59E0B; --series-4: #A78BFA;
    --series-5: #F472B6; --series-6: #A3E635;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 15px/1.5 "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 28px 16px 60px; }
  header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 12px; margin-bottom: 20px; }
  h1 { font-size: 28px; margin: 0 0 4px; letter-spacing: -.01em; }
  h2 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: var(--muted); margin: 0; }
  .controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  select, button { font: inherit; color: var(--ink); background: var(--surface); border: 1px solid var(--line);
                   border-radius: 8px; padding: 6px 10px; }
  button { cursor: pointer; }
  section { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 20px; margin-bottom: 18px; }
  .hint { color: var(--muted); font-size: 13.5px; margin: 0 0 14px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 18px; }
  .tile { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; }
  .tile b { display: block; font-size: 26px; color: var(--accent); line-height: 1.1; }
  .tile span { color: var(--muted); font-size: 13px; }
  .grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 18px; }
  .chart { position: relative; height: 320px; }
  .scroll { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 14px; }
  th, td { padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
  th { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); cursor: pointer; user-select: none; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  td.heat { text-align: center; font-variant-numeric: tabular-nums; min-width: 72px; }
  .empty { color: var(--muted); padding: 20px 0; }
  footer { color: var(--muted); font-size: 13px; text-align: center; margin-top: 24px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>__TITLE__</h1>
      <p class="sub" id="meta"></p>
    </div>
    <div class="controls">
      <label>Difficulty <select id="difficulty"></select></label>
      <button id="theme" type="button" title="Toggle light/dark">Theme</button>
    </div>
  </header>

  <div class="tiles" id="tiles"></div>

  <section>
    <h2>Model leaderboard</h2>
    <p class="hint">Average score (1–5) per dimension over all questions, runs and judges. Click a column to sort.</p>
    <div class="scroll"><table id="leaderboard"></table></div>
  </section>

  <section>
    <h2>Scores by dimension</h2>
    <p class="hint">Where each model is strong or weak.</p>
    <div class="chart"><canvas id="dimChart"></canvas></div>
  </section>

  <section>
    <h2>How the judges differ</h2>
    <p class="hint">Mean absolute difference (MAD) is the average gap between two judges' scores for the same answer. 0 means they always agree.</p>
    <div class="grid2">
      <div><h3 class="sub">Average score given, per model</h3><div class="chart"><canvas id="judgeModelChart"></canvas></div></div>
      <div><h3 class="sub">Average score given, per dimension</h3><div class="chart"><canvas id="judgeDimChart"></canvas></div></div>
    </div>
    <div class="scroll" style="margin-top:16px"><table id="agreement"></table></div>
  </section>

  <section>
    <h2>Scores per question</h2>
    <p class="hint">Average score over all dimensions and judges for each question and model. Darker means higher, relative to the lowest and highest value in the table.</p>
    <div class="scroll"><table id="heatScores"></table></div>
  </section>

  <section>
    <h2>Judge disagreement per question</h2>
    <p class="hint">Mean absolute difference between judges for each question and model, averaged over dimensions. Darker means the judges disagree more, relative to the rest of the table.</p>
    <div class="scroll"><table id="heatMad"></table></div>
  </section>

  <section>
    <h2>Every judgement</h2>
    <p class="hint">Each judge's scores for each answer. Cases are shown by ID only; no case content is published.</p>
    <div class="controls" style="margin-bottom:12px">
      <label>Question <select id="fItem"></select></label>
      <label>Model <select id="fModel"></select></label>
      <label>Judge <select id="fJudge"></select></label>
    </div>
    <div class="scroll"><table id="explorer"></table></div>
  </section>

  <footer>Generated by <code>python -m eval.site</code> from the saved eval results.</footer>
</div>

<script id="eval-data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById("eval-data").textContent);
const dims = D.dimensions;
const itemsByKey = Object.fromEntries(D.items.map(i => [i.key, i]));
const answersByKey = Object.fromEntries(D.answers.map(a => [a.key, a]));
const charts = {};
let difficulty = "all";

const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const mean = xs => xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null;
const fmt = (x, d = 2) => x == null ? "–" : x.toFixed(d);
const avg = xs => mean(xs.filter(x => x != null));
const el = (tag, attrs = {}, text) => { const e = document.createElement(tag); Object.assign(e, attrs); if (text != null) e.textContent = text; return e; };
const series = i => css(`--series-${(i % 6) + 1}`);
const itemLabel = i => `${i.caseId}${i.question !== "question1" ? " (" + i.question.replace("question", "Q") + ")" : ""}`;

function visible(j) {
  const a = answersByKey[j.answer];
  return a && (difficulty === "all" || itemsByKey[a.item].difficulty === difficulty);
}
function visibleAnswers() { return D.answers.filter(a => difficulty === "all" || itemsByKey[a.item].difficulty === difficulty); }
function overall(j) { return mean(j.scores); }

// Pairs of judgements on the same answer, for agreement stats
function judgePairs(js) {
  const byAnswer = {};
  js.forEach(j => (byAnswer[j.answer] ||= []).push(j));
  const pairs = [];
  Object.values(byAnswer).forEach(list => {
    for (let x = 0; x < list.length; x++) for (let y = x + 1; y < list.length; y++) pairs.push([list[x], list[y]]);
  });
  return pairs;
}

function renderTiles(js) {
  const answers = visibleAnswers();
  const pairs = judgePairs(js);
  const diffs = pairs.flatMap(([a, b]) => a.scores.map((s, i) => Math.abs(s - b.scores[i])));
  const tiles = [
    [D.models.length, "models"],
    [new Set(answers.map(a => a.item)).size, "questions"],
    [answers.length, "answers"],
    [js.length, "judgements"],
    [fmt(avg(js.map(overall))), "average score (1–5)"],
    [fmt(mean(diffs)), "judge MAD"],
  ];
  const box = document.getElementById("tiles");
  box.replaceChildren(...tiles.map(([v, l]) => { const t = el("div", { className: "tile" }); t.append(el("b", {}, String(v)), el("span", {}, l)); return t; }));
}

function sortableTable(table, headers, rows, numericFrom) {
  let sortCol = null, dir = -1;
  function draw() {
    const sorted = sortCol == null ? rows : [...rows].sort((a, b) => {
      const x = a[sortCol].sort ?? a[sortCol].v, y = b[sortCol].sort ?? b[sortCol].v;
      return (x == null) - (y == null) || (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
    const thead = el("thead"), tr = el("tr");
    headers.forEach((h, i) => {
      const th = el("th", { className: i >= numericFrom ? "num" : "" }, h + (sortCol === i ? (dir < 0 ? " ▼" : " ▲") : ""));
      th.onclick = () => { dir = sortCol === i ? -dir : -1; sortCol = i; draw(); };
      tr.append(th);
    });
    thead.append(tr);
    const tbody = el("tbody");
    sorted.forEach(r => { const row = el("tr"); r.forEach((c, i) => row.append(el("td", { className: i >= numericFrom ? "num" : "" }, c.t ?? String(c.v ?? "–")))); tbody.append(row); });
    table.replaceChildren(thead, tbody);
  }
  draw();
}

function renderLeaderboard(js) {
  const answers = visibleAnswers();
  const rows = D.models.map(m => {
    const mj = js.filter(j => answersByKey[j.answer].model === m);
    const ma = answers.filter(a => a.model === m);
    const o = avg(mj.map(overall));
    const per = dims.map((_, i) => avg(mj.map(j => j.scores[i])));
    const cost = ma.reduce((s, a) => s + (a.cost || 0), 0);
    return [{ v: m }, { v: o, t: fmt(o) }, ...per.map(v => ({ v, t: fmt(v) })),
            { v: ma.length }, { v: avg(ma.map(a => a.words)), t: fmt(avg(ma.map(a => a.words)), 0) },
            { v: avg(ma.map(a => a.latency)), t: fmt(avg(ma.map(a => a.latency)), 1) }, { v: cost, t: "$" + cost.toFixed(3) }];
  });
  sortableTable(document.getElementById("leaderboard"),
    ["Model", "Overall", ...dims.map(d => d.label), "Answers", "Avg words", "Avg latency (s)", "Answer cost"], rows, 1);
}

function barChart(id, labels, datasets, opts = {}) {
  charts[id]?.destroy();
  const ink = css("--ink"), line = css("--line"), muted = css("--muted");
  charts[id] = new Chart(document.getElementById(id), {
    type: "bar",
    data: { labels, datasets: datasets.map((d, i) => ({ borderRadius: 4, backgroundColor: series(i), ...d })) },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        y: { min: opts.min ?? 1, max: opts.max ?? 5, ticks: { color: muted }, grid: { color: line } },
        x: { ticks: { color: muted }, grid: { display: false } },
      },
      plugins: {
        legend: { labels: { color: ink, boxWidth: 12 } },
        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${fmt(c.parsed.y)}` } },
      },
    },
  });
}

function renderDimChart(js) {
  barChart("dimChart", dims.map(d => d.label), D.models.map(m => ({
    label: m, data: dims.map((_, i) => avg(js.filter(j => answersByKey[j.answer].model === m).map(j => j.scores[i]))),
  })));
}

function renderJudges(js) {
  barChart("judgeModelChart", D.models, D.judges.map(judge => ({
    label: judge, data: D.models.map(m => avg(js.filter(j => j.judge === judge && answersByKey[j.answer].model === m).map(overall))),
  })));
  barChart("judgeDimChart", dims.map(d => d.label), D.judges.map(judge => ({
    label: judge, data: dims.map((_, i) => avg(js.filter(j => j.judge === judge).map(j => j.scores[i]))),
  })));

  const pairs = judgePairs(js);
  const rows = dims.map((d, i) => {
    const diffs = pairs.map(([a, b]) => Math.abs(a.scores[i] - b.scores[i]));
    const exact = diffs.length ? 100 * diffs.filter(x => x === 0).length / diffs.length : null;
    const within = diffs.length ? 100 * diffs.filter(x => x <= 1).length / diffs.length : null;
    return [{ v: d.label }, { v: mean(diffs), t: fmt(mean(diffs)) }, { v: exact, t: exact == null ? "–" : exact.toFixed(0) + "%" },
            { v: within, t: within == null ? "–" : within.toFixed(0) + "%" }, { v: diffs.length }];
  });
  sortableTable(document.getElementById("agreement"), ["Dimension", "MAD", "Exact match", "Within 1 point", "Answer pairs"], rows, 1);
}

// Cell colour intensity runs from the lowest to the highest value in the table, so small differences stay visible
function heatTable(tableId, cellValue, colour, digits) {
  const table = document.getElementById(tableId);
  const items = D.items.filter(i => difficulty === "all" || i.difficulty === difficulty);
  const values = items.flatMap(item => D.models.map(m => cellValue(item, m))).filter(v => v != null);
  const lo = Math.min(...values), hi = Math.max(...values);
  const scale = v => hi > lo ? (v - lo) / (hi - lo) : 0.5;
  const thead = el("thead"), hr = el("tr");
  hr.append(el("th", {}, "Question"), el("th", {}, "Difficulty"), ...D.models.map(m => el("th", { className: "num" }, m)));
  thead.append(hr);
  const tbody = el("tbody");
  items.forEach(item => {
    const tr = el("tr");
    tr.append(el("td", {}, itemLabel(item)), el("td", {}, item.difficulty));
    D.models.forEach(m => {
      const v = cellValue(item, m);
      const td = el("td", { className: "heat" }, fmt(v, digits));
      if (v != null) td.style.background = colour(scale(v));
      tr.append(td);
    });
    tbody.append(tr);
  });
  table.replaceChildren(thead, tbody);
}

function renderHeatmaps(js) {
  const forCell = (item, m) => js.filter(j => { const a = answersByKey[j.answer]; return a.item === item.key && a.model === m; });
  heatTable("heatScores", (item, m) => avg(forCell(item, m).map(overall)),
    t => `rgba(${css("--accent-rgb")}, ${0.06 + t * 0.7})`, 2);
  heatTable("heatMad", (item, m) => {
    const pairs = judgePairs(forCell(item, m));
    return pairs.length ? mean(pairs.flatMap(([a, b]) => a.scores.map((s, i) => Math.abs(s - b.scores[i])))) : null;
  }, t => `rgba(${css("--warn-rgb")}, ${0.04 + t * 0.7})`, 2);
}

function fillSelect(id, options, label) {
  const s = document.getElementById(id), current = s.value;
  s.replaceChildren(el("option", { value: "" }, `All ${label}`), ...options.map(([v, t]) => el("option", { value: v }, t)));
  if (options.some(([v]) => v === current)) s.value = current;
}

function renderExplorer(js) {
  fillSelect("fItem", D.items.filter(i => difficulty === "all" || i.difficulty === difficulty).map(i => [i.key, itemLabel(i)]), "questions");
  fillSelect("fModel", D.models.map(m => [m, m]), "models");
  fillSelect("fJudge", D.judges.map(j => [j, j]), "judges");
  const fItem = document.getElementById("fItem").value, fModel = document.getElementById("fModel").value, fJudge = document.getElementById("fJudge").value;
  const rows = js.filter(j => { const a = answersByKey[j.answer]; return (!fItem || a.item === fItem) && (!fModel || a.model === fModel) && (!fJudge || j.judge === fJudge); });

  const table = document.getElementById("explorer");
  const thead = el("thead"), hr = el("tr");
  ["Question", "Model", "Run", "Judge", ...dims.map(d => d.label), "Avg", "Key points (full / partial / missed)"].forEach((h, i) =>
    hr.append(el("th", { className: i >= 4 && i < 4 + dims.length + 1 ? "num" : "" }, h)));
  thead.append(hr);
  const tbody = el("tbody");
  if (!rows.length) { const tr = el("tr"); tr.append(el("td", { colSpan: 12, className: "empty" }, "No judgements match these filters.")); tbody.append(tr); }
  rows.forEach(j => {
    const a = answersByKey[j.answer], item = itemsByKey[a.item];
    const tr = el("tr");
    tr.append(el("td", {}, itemLabel(item)), el("td", {}, a.model), el("td", {}, String(a.run)), el("td", {}, j.judge),
      ...j.scores.map(s => el("td", { className: "num" }, String(s))), el("td", { className: "num" }, fmt(overall(j))),
      el("td", {}, `${j.keyPoints.full} / ${j.keyPoints.partial} / ${j.keyPoints.none}`));
    tbody.append(tr);
  });
  table.replaceChildren(thead, tbody);
}

function renderAll() {
  const js = D.judgements.filter(visible);
  renderTiles(js); renderLeaderboard(js); renderDimChart(js); renderJudges(js); renderHeatmaps(js); renderExplorer(js);
}

document.getElementById("meta").textContent =
  `Generated ${D.generatedAt} · ${D.models.length} models · ${D.judges.length} judges · scores 1 (lowest) to 5 (highest)`;
const diffSelect = document.getElementById("difficulty");
diffSelect.replaceChildren(el("option", { value: "all" }, "All"),
  ...[...new Set(D.items.map(i => i.difficulty))].sort().map(d => el("option", { value: d }, d)));
diffSelect.onchange = () => { difficulty = diffSelect.value; renderAll(); };
["fItem", "fModel", "fJudge"].forEach(id => document.getElementById(id).onchange = () => renderExplorer(D.judgements.filter(visible)));
document.getElementById("theme").onclick = () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  renderAll();
};
renderAll();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
