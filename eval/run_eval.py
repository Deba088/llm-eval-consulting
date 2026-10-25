"""Ask every candidate model every golden-dataset question, score the answers with judge models, save to Excel.

Steps:
    1. For each case and each questionN/answerN pair, send the filled candidate prompt to every candidate model.
    2. Send the filled judge prompt (case, question, golden answer, candidate answer) to every judge model.
       Judges never see which model wrote the answer.
    3. Update results/eval_results.xlsx with a summary per model plus every score, answer and reason.

Answers and judgements are saved as they arrive in results/*.jsonl, so an interrupted run picks up where
it stopped and nothing is paid for twice. After every run the Excel file is updated in place with all saved
results (every model and case evaluated so far), not just the ones from this run. Settings live in eval/config.yaml.

Usage (from the project root):
    python -m eval.run_eval --dry-run                   # print the prompts for the first case, no API calls
    python -m eval.run_eval                             # every case, every model
    python -m eval.run_eval --cases q001,q002           # only these cases
    python -m eval.run_eval --models sol --cases q003   # only models whose ID contains "sol"
    python -m eval.run_eval --cases q001 --rerun        # ask again and replace earlier answers and scores
    python -m eval.run_eval --cases q001 --rejudge      # keep the answers, score them again
    python -m eval.run_eval --report-only               # update the Excel file from saved results
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from langchain_core.runnables import RunnableLambda

from . import ROOT
from .llm import candidate_chain, judge_chain, load_pricing, make_llm, make_prompt, message_text, model_provider, usage
from .results import JsonlStore, answer_key, is_current, write_report

DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


# ---------- dataset ----------

def join_text(blocks):
    """Concatenate the text of a list of {type, text} blocks."""
    return "\n".join(b.get("text", "") for b in blocks or [] if b.get("type") == "text").strip()


def load_items(dataset_path):
    """One item per (case, questionN) that has a matching answerN."""
    with open(dataset_path, encoding="utf-8") as f:
        cases = yaml.safe_load(f)["case-studies"]
    items = []
    for case in cases:
        for key in sorted(k for k in case if re.fullmatch(r"question\d+", k)):
            answer_field = key.replace("question", "answer")
            if answer_field not in case:
                continue
            items.append({
                "case_id": case["id"],
                "case_name": case.get("case_name", ""),
                "difficulty": case.get("difficulty", ""),
                "question_key": key,
                "context": join_text(case.get("context")),
                "question": join_text(case[key]),
                "golden": join_text(case[answer_field]),
            })
    return items


# ---------- running candidates and judges ----------

def run_batch(label, tasks, fn, workers):
    """Run fn over tasks in parallel with LangChain's batch_as_completed; failures are logged and skipped."""
    if not tasks:
        print(f"{label}: nothing to do")
        return
    print(f"{label}: {len(tasks)} calls")
    failures = 0
    runner = RunnableLambda(fn)
    results = runner.batch_as_completed(tasks, config={"max_concurrency": workers}, return_exceptions=True)
    for done, (i, result) in enumerate(results, start=1):
        if isinstance(result, Exception):
            failures += 1
            print(f"  [{done}/{len(tasks)}] FAIL  {tasks[i]['desc']}: {type(result).__name__}: {str(result)[:300]}")
        else:
            print(f"  [{done}/{len(tasks)}] ok    {tasks[i]['desc']}")
    if failures:
        print(f"{label}: {failures} failed; run again to retry them")


def run_candidates(cfg, items, models, answers, pricing, workers, rerun):
    prompt = make_prompt(cfg["candidate_prompt"])
    chains = {m: candidate_chain(prompt, make_llm(cfg, cfg["candidates"], m)) for m in models}

    def answer(task):
        item, model, run = task["item"], task["model"], task["run"]
        start = time.time()
        message = chains[model].invoke({"context": item["context"], "question": item["question"]})
        text = message_text(message)
        if not text:
            raise ValueError("empty answer")
        answers.add({"key": answer_key(item, model, run), "case_id": item["case_id"],
                     "question_key": item["question_key"], "model": model, "run": run,
                     "words": len(text.split()), "latency_s": round(time.time() - start, 2),
                     **usage(message, model, pricing), "text": text,
                     "created_at": datetime.now().isoformat(timespec="seconds")})

    tasks = [{"item": item, "model": model, "run": run,
              "desc": f"{item['case_id']} {item['question_key']} {model} run {run}"}
             for item in items for model in models
             for run in range(1, cfg.get("runs_per_case", 1) + 1)
             if rerun or answer_key(item, model, run) not in answers]
    run_batch("Candidate answers", tasks, answer, workers)


def run_judges(cfg, items, models, judges, answers, judgements, pricing, workers, rejudge):
    prompt = make_prompt(cfg["judge_prompt"])
    chains = {j: judge_chain(prompt, make_llm(cfg, cfg["judges"], j)) for j in judges}
    items_by_key = {(i["case_id"], i["question_key"]): i for i in items}

    def judge(task):
        item, a, judge_model = task["item"], task["answer"], task["judge"]
        out = chains[judge_model].invoke({"context": item["context"], "question": item["question"],
                                          "golden_answer": item["golden"], "candidate_answer": a["text"]})
        judgements.add({"key": f"{a['key']}|{judge_model}", "answer_key": a["key"], "judge": judge_model,
                        "answer_created_at": a.get("created_at"),
                        "cost_usd": usage(out["message"], judge_model, pricing)["cost_usd"],
                        "judgement": out["judgement"].model_dump(),
                        "created_at": datetime.now().isoformat(timespec="seconds")})

    answers_by_key = dict(answers.records)
    tasks = []
    for a in list(answers.records.values()):
        item = items_by_key.get((a["case_id"], a["question_key"]))
        if item is None or a["model"] not in models:
            continue
        for judge_model in judges:
            existing = judgements.records.get(f"{a['key']}|{judge_model}")
            if rejudge or existing is None or not is_current(existing, answers_by_key):
                tasks.append({"item": item, "answer": a, "judge": judge_model,
                              "desc": f"{a['case_id']} {a['question_key']} {a['model']} run {a['run']} <- {judge_model}"})
    run_batch("Judgements", tasks, judge, workers)


# ---------- command line ----------

def print_dry_run(cfg, items, models, judges):
    item = items[0]
    print("=" * 30, "CANDIDATE PROMPT", item["case_id"], item["question_key"], "=" * 30)
    candidate = make_prompt(cfg["candidate_prompt"]).invoke({"context": item["context"], "question": item["question"]})
    print(candidate.to_messages()[0].content)
    print("=" * 30, "JUDGE PROMPT (with a placeholder answer)", "=" * 30)
    judge = make_prompt(cfg["judge_prompt"]).invoke({"context": item["context"], "question": item["question"],
                                                     "golden_answer": item["golden"],
                                                     "candidate_answer": "<candidate answer here>"})
    print(judge.to_messages()[0].content)
    runs = cfg.get("runs_per_case", 1)
    print(f"\nA full run makes {len(items) * len(models) * runs} candidate calls and "
          f"{len(items) * len(models) * runs * len(judges)} judge calls "
          f"({len(items)} questions x {len(models)} models x {runs} runs x {len(judges)} judges).")


def main():
    parser = argparse.ArgumentParser(prog="python -m eval.run_eval", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="settings file (default eval/config.yaml)")
    parser.add_argument("--models", help="comma-separated parts of candidate model IDs to run, e.g. sol,luna")
    parser.add_argument("--cases", help="comma-separated case IDs to run, e.g. q001,q002")
    parser.add_argument("--dry-run", action="store_true", help="print the prompts for the first question and exit")
    parser.add_argument("--rerun", action="store_true",
                        help="ask the selected models the selected cases again, replacing earlier answers and scores")
    parser.add_argument("--rejudge", action="store_true",
                        help="score the selected answers again (e.g. after changing the rubric), keeping the answers")
    parser.add_argument("--report-only", action="store_true", help="update the Excel file without calling any API")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for spec in cfg["candidates"]["models"] + cfg["judges"]["models"]:
        if spec["provider"] not in cfg["providers"]:
            sys.exit(f"{spec['id']} uses provider '{spec['provider']}', which is not under 'providers' in {args.config}.")

    all_items = load_items(ROOT / cfg["dataset"])
    case_filter = {c.strip() for c in args.cases.split(",")} if args.cases else None
    items = [i for i in all_items if not case_filter or i["case_id"] in case_filter]
    if not items:
        sys.exit("No cases with matching questionN/answerN found.")
    unknown_cases = (case_filter or set()) - {i["case_id"] for i in items}
    if unknown_cases:
        print(f"Warning: case(s) not found in the dataset: {', '.join(sorted(unknown_cases))}")

    config_models = [spec["id"] for spec in cfg["candidates"]["models"]]
    models = config_models
    if args.models:
        parts = [p.strip().lower() for p in args.models.split(",")]
        models = [m for m in config_models if any(p in m.lower() for p in parts)]
        if not models:
            sys.exit(f"No candidate model in {args.config} matches --models {args.models}.")
    judges = [spec["id"] for spec in cfg["judges"]["models"]]
    for judge in set(judges) & set(models):
        print(f"Warning: {judge} is both a candidate and a judge; it may favour its own answers.")

    if args.dry_run:
        print_dry_run(cfg, items, models, judges)
        return

    out_dir = ROOT / cfg["output_dir"]
    out_dir.mkdir(exist_ok=True)
    answers = JsonlStore(out_dir / "answers.jsonl")
    judgements = JsonlStore(out_dir / "judgements.jsonl")

    if not args.report_only:
        needed = {cfg["providers"][model_provider(cfg, m)]["api_key_env"] for m in models + judges}
        missing = sorted(env for env in needed if not os.environ.get(env))
        if missing:
            sys.exit(f"Set the {', '.join(missing)} environment variable(s) (or use --dry-run / --report-only).")
        workers = cfg["api"].get("max_workers", 2)
        pricing = load_pricing(cfg, models + judges)
        run_candidates(cfg, items, models, answers, pricing, workers, args.rerun)
        run_judges(cfg, items, models, judges, answers, judgements, pricing, workers, args.rejudge)

    write_report(out_dir / "eval_results.xlsx", all_items, config_models, judges, answers, judgements)


if __name__ == "__main__":
    main()
