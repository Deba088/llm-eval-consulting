"""Print the size of the context, question(s) and answer(s) for every case in the golden dataset.

Usage:
    python dataset_stats.py [path/to/manifest.yaml]
"""

import re
import sys
from pathlib import Path
import math

import yaml

DEFAULT_MANIFEST = Path(__file__).parent / "golden_dataset" / "manifest.yaml"


def join_text(blocks):
    """Concatenate the text of a list of {type, text} blocks."""
    if not blocks:
        return ""
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def size(text):
    return {"chars": len(text), "words": len(text.split())}


def field_order(key):
    """Sort context first, then question1, answer1, question2, answer2, ..."""
    if key == "context":
        return (0, 0, 0)
    m = re.fullmatch(r"(question|answer)(\d+)", key)
    return (1, int(m.group(2)), 0 if m.group(1) == "question" else 1)


def main():
    manifest = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MANIFEST
    with open(manifest, encoding="utf-8") as f:
        cases = yaml.safe_load(f)["case-studies"]

    header = f"{'ID':<6}{'Case name':<24}{'Field':<11}{'Chars':>8}{'Words':>8}{'Token':>8}"
    print(header)
    print("-" * len(header))

    totals = {}
    for case in cases:
        fields = [k for k in case if k == "context" or re.fullmatch(r"(question|answer)\d+", k)]
        for i, key in enumerate(sorted(fields, key=field_order)):
            s = size(join_text(case[key]))
            kind = re.sub(r"\d+", "", key)
            s["tokens"] = math.ceil(s["chars"]/4)
            totals.setdefault(kind, {"chars": 0, "words": 0, "tokens": 0})
            totals[kind]["chars"] += s["chars"]
            totals[kind]["words"] += s["words"]
            totals[kind]["tokens"] += s["tokens"]
            case_id = case["id"] if i == 0 else ""
            name = case["case_name"] if i == 0 else ""
            print(f"{case_id:<6}{name:<24}{key:<11}{s['chars']:>8}{s['words']:>8}{s["tokens"]:>8}")
        print()

    n = len(cases)
    print(f"Totals across {n} cases")
    print("-" * len(header))
    for kind, t in totals.items():
        print(f"{kind:<41}{t['chars']:>8}{t['words']:>8}{t["tokens"]:>8}   "
              f"(avg {t['chars'] // n} chars / {t['words'] // n} words per case / {t['tokens'] // n} tokens per case)")


if __name__ == "__main__":
    main()
