# llm-eval-consulting
Eval LLM models for consulting case studies: how well can a model structure a business problem (issue tree, MECE, client-specific) from the information in a case?

## Project structure

```
llm-eval-consulting/
├── golden_dataset/
│   └── manifest.yaml          # Golden cases: context, question(s) and model answer(s)
├── prompts/
│   └── model_instruction.txt  # User prompt sent to each model ({context} and {question} placeholders)
├── dataset_stats.py           # Size of context / question / answer per case (chars, words, tokens)
├── model_benchmarks.py        # Public benchmark scores, pricing and speed per model -> Excel
├── requirements.txt
└── .gitignore
```

The repo only holds **sample** versions of `golden_dataset/manifest.yaml` and `prompts/model_instruction.txt`. Local edits to them are hidden from git (see [Keeping the real dataset private](#keeping-the-real-dataset-private)).

## Setup

Requires Python 3.12+.

```bash
python -m venv venv
```

```bash
venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

On macOS/Linux, activate with `source venv/bin/activate`.

## Golden dataset format

`golden_dataset/manifest.yaml` is a list of cases under `case-studies`. Each field is a list of text blocks:

```yaml
case-studies:
  - id: q001
    case_name: Fit Pro
    difficulty: easy            # easy | medium | hard
    context:
      - type: text
        text: Background, problem definition and additional information...
    question1:
      - type: text
        text: How would you structure your approach...?
    answer1:
      - type: text
        text: |
          1. Top-level branch
            a. Sub-branch
```

Add follow-up questions as `question2` / `answer2` and so on. Keep context to what a candidate would see: no interviewer notes such as "If the candidate asks...".

## Prompt

`prompts/model_instruction.txt` is the user-role prompt sent to every model. It asks for an issue tree only (no solving or recommendation) in the same `1.` / `a.` format as the golden answers, under 250 words. Fill it with:

```python
prompt = template.format(context=context_text, question=question_text)
```

where `context_text` and `question_text` are the joined `text` blocks of `context` and `questionN`.

## Scripts

### dataset_stats.py: dataset size

Prints characters, words and estimated tokens (chars / 4) for each case's context, question(s) and answer(s), plus totals and averages.

```bash
python dataset_stats.py
```

```bash
python dataset_stats.py path/to/other_manifest.yaml
```

### model_benchmarks.py: benchmark scores to Excel

Fetches model data from the [Artificial Analysis API](https://artificialanalysis.ai/documentation) and writes a table with Model Name, Creator, one column per benchmark, Input cost, Output cost and Speed to `model_benchmarks.xlsx`.

1. Get a free API key at artificialanalysis.ai.
2. Set it in your terminal (PowerShell):

   ```powershell
   $env:AA_API_KEY = "your-key"
   ```

3. Run:

   ```bash
   python model_benchmarks.py --list
   ```

   ```bash
   python model_benchmarks.py --benchmarks gpqa,hle --sort gpqa
   ```

   ```bash
   python model_benchmarks.py --creator anthropic,openai,google --output shortlist.xlsx
   ```

| Option | What it does |
|---|---|
| `--list` | Show available benchmark names and how many models have each |
| `--benchmarks a,b,c` | Benchmark columns to include (default: all) |
| `--creator a,b` | Keep only these model creators (slugs, e.g. `anthropic`) |
| `--sort name` | Sort highest first by a benchmark, `input`, `output` or `speed` (default: model name) |
| `--top N` | Rows printed in the terminal (default 20); the Excel file always gets all rows |
| `--output file.xlsx` | Excel file to write (default `model_benchmarks.xlsx`) |
| `--refresh` | Ignore the 24-hour cache in `.cache/` and fetch fresh data |
| `--from-file f.json` | Read a saved API response instead of calling the API |

The API allows 1,000 requests per day, so responses are cached for 24 hours. Close the Excel file before re-running, or the save fails.

## Keeping the real dataset private

`.gitignore` lists `golden_dataset/` and `prompts/`, but the sample files were committed before that, so git still tracks them. To keep your local edits out of git on this machine:

```bash
git update-index --skip-worktree golden_dataset/manifest.yaml prompts/model_instruction.txt
```

To commit a new sample version, turn it off first, commit, then turn it back on:

```bash
git update-index --no-skip-worktree golden_dataset/manifest.yaml prompts/model_instruction.txt
```

This setting is per clone, so run it again on any other machine.
