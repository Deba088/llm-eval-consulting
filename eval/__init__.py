"""Evaluate how well LLMs structure consulting cases, scored by judge LLMs against a golden dataset.

Modules:
    llm       LangChain side: judge output schema, chat model clients, prompt chains, pricing
    results   Saved answers/judgements (JSONL) and the Excel report
    run_eval  Command line entry point: loads the dataset, runs candidates and judges, writes the report

Run from the project root:
    python -m eval.run_eval --help
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # project root; paths in eval/config.yaml are relative to it
