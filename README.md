# llm-eval-consulting
Eval LLM models for consulting case studies: how well can a model structure a business problem (issue tree, MECE, client-specific) from the information in a case?

## Project structure

```
llm-eval-consulting/
├── golden_dataset/
│   └── manifest.yaml          # Golden cases: context, question(s) and model answer(s)
├── prompts/
│   ├── model_instruction.txt  # User prompt sent to each model ({context} and {question} placeholders)
│   └── judge_rubric.txt       # Judge prompt: scores an answer vs. the golden answer, 1-5 on six dimensions
├── eval/                      # Eval pipeline (run with: python -m eval.run_eval)
│   ├── config.yaml            # Candidate models, judge models and run settings
│   ├── run_eval.py            # Command line entry point: dataset, candidate and judge runs
│   ├── llm.py                 # LangChain: model clients, prompt chains, judge output schema, pricing
│   ├── results.py             # Saved results (results/*.jsonl) and the Excel report
│   └── site.py                # Builds the results website (python -m eval.site)
├── docs/                      # Generated results website, served by GitHub Pages
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
    case_name: Sample Case
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

### eval/: evaluate models on the golden dataset

For every case and every `questionN` / `answerN` pair:

1. Fills `prompts/model_instruction.txt` and sends it to each candidate model.
2. Fills `prompts/judge_rubric.txt` with the case, question, golden answer and candidate answer, and sends it to each judge model. Judges don't see which model wrote the answer.
3. Writes `results/eval_results.xlsx`.

Built with LangChain:

| Piece | LangChain component |
|---|---|
| Model calls | `ChatOpenAI` (`langchain-openai`) for OpenAI models and `ChatGoogleGenerativeAI` (`langchain-google-genai`) for Gemini; both retry rate limits and server errors |
| Prompts | `ChatPromptTemplate` filled from the two files in `prompts/` |
| Judge output | `PydanticOutputParser` checks the JSON has six whole-number scores from 1 to 5 |
| Bad judge replies | `.with_retry()` re-asks the judge up to 3 times when its reply doesn't parse |
| Parallel calls | `batch_as_completed()` with `max_concurrency` from `eval/config.yaml` |

Models are called directly at each provider. In `eval/config.yaml`, each model has an `id` and a `provider` (`openai` or `google`). The current setup:

| Role | Models |
|---|---|
| Candidates | `gpt-5.6-terra` ($2 / $12), `gpt-6-sol` ($2 / $10), `gpt-5.6-luna` ($0.20 / $1.20) |
| Judges | `gpt-6.1-sol`, `gpt-6-luna` |

Costs are estimated from token counts and OpenRouter's public price list (no OpenRouter key needed). Models marked `free_tier` are counted as $0. Gemini is set up but commented out in `eval/config.yaml`; un-comment it and set `GOOGLE_API_KEY` (from aistudio.google.com) to add it back.

1. Get an OpenAI API key at platform.openai.com.
2. Set it in your terminal (PowerShell):

   ```powershell
   $env:OPENAI_API_KEY = "your-openai-key"
   ```

3. Check the prompts and the number of calls, without calling any API:

   ```bash
   python -m eval.run_eval --dry-run
   ```

4. Try a small run first, then the full run:

   ```bash
   python -m eval.run_eval --cases q001
   ```

   ```bash
   python -m eval.run_eval
   ```

| Option | What it does |
|---|---|
| `--dry-run` | Print the filled prompts for the first question and the number of API calls a full run makes |
| `--models a,b` | Only run candidate models whose ID contains one of these strings |
| `--cases q001,q002` | Only run these case IDs |
| `--rerun` | Ask the selected models the selected cases again, replacing their earlier answers and scores (e.g. after editing a case) |
| `--rejudge` | Keep the selected answers but score them again (e.g. after editing the rubric) |
| `--report-only` | Update the Excel file from saved results without calling any API |
| `--config file.yaml` | Use a different settings file |

**Updating the Excel file**

`results/eval_results.xlsx` is created on the first run and updated in place after every later run. It always shows **all saved results**: every model and case evaluated so far, not just the ones in the latest run. For example:

```bash
python -m eval.run_eval --cases q001,q002
```

```bash
python -m eval.run_eval --cases q003
```

After the second command, the Excel file has results for q001, q002 and q003.

- **Your own sheets stay.** Sheets you add (e.g. your own weighted score) are kept, and formulas pointing at the generated sheets keep working.
  - Refer to models by name (e.g. `XLOOKUP` on the Model column), not by fixed cell. Row order can change when models are added or removed.
- **Only current scores count.** A score is included only if it was made by a judge currently in `eval/config.yaml`, on the latest version of the answer.
  - If you change the judges, the old judges' scores drop out of the Excel file. They stay in `results/judgements.jsonl`.
- **Close the file before a run.** If it's open in Excel, saving fails. The results are still saved in `results/*.jsonl`; close the file and run `python -m eval.run_eval --report-only`.

**Excel sheets**

| Sheet | Contents |
|---|---|
| Summary | One row per model: average score per dimension (over cases, runs and judges), average words, latency and cost |
| By difficulty | The same averages split by easy / medium / hard |
| Scores | One row per answer and judge, with key points covered / partly covered / missed, strengths and weaknesses |
| Judge reasoning | The judge's reason for each score and its key-point checklist |
| Answers | Every model answer with words, latency, tokens and cost |
| Judge agreement | How often the judges give the same score (mean difference, % exact, % within 1 point) |

**Notes**

- Results are saved to `results/answers.jsonl` and `results/judgements.jsonl` as they arrive. Re-running skips anything already done, so an interrupted run resumes and failed calls are retried. To redo some results, use `--rerun` or `--rejudge` with `--cases` / `--models`. To start completely fresh, delete the `results/` folder.
- A judge tends to favour answers from its own model family. Both judges are OpenAI models, so check a few Gemini scores by hand before concluding it is weaker.
- On Google's free tier, Google may use the content you send (including the golden dataset) to improve its products. Free-tier rate limits are low, so `max_workers` is set to 2; rate-limited calls are retried automatically.
- OpenAI reasoning models only accept their default temperature, so `temperature` is `null` for the judges.
- Set `runs_per_case` above 1 in `eval/config.yaml` for more reliable averages; each run is a separate API call.
- `results/` is in `.gitignore`.

### eval/site.py: results website (GitHub Pages)

Builds `docs/index.html`, a single static page with all data embedded. Charts come from Chart.js on a CDN. It shows:

| Section | Contents |
|---|---|
| Overview | Number of models, questions, answers and judgements; average score; judge MAD |
| Model leaderboard | Average score per dimension for each model, plus words, latency and cost (sortable) |
| Scores by dimension | Bar chart of each model across the six dimensions |
| How the judges differ | Average score each judge gives per model and per dimension, plus agreement per dimension (MAD, exact match, within 1 point) |
| Scores per question | Question x model heatmap of average scores |
| Judge disagreement per question | Question x model heatmap of how far apart the judges are |
| Every judgement | Filterable table of every score (by case ID, model and judge) |

A difficulty filter at the top applies to the whole page, and there's a light/dark toggle.

**Update the site after each eval run:**

```bash
python -m eval.run_eval
```

```bash
python -m eval.site
```

```bash
git add docs/
```

```bash
git commit -m "Update eval results site"
```

```bash
git push
```

**Turn on GitHub Pages (once):** in the repository on GitHub, go to **Settings → Pages**. Under **Build and deployment**, choose **Deploy from a branch**, pick the branch you push to (e.g. `main`) and the **/docs** folder, then **Save**. The site appears at `https://<your-username>.github.io/<repo-name>/` a minute or two after each push.

**Privacy:**
- **The site is public.** GitHub Pages sites are public, even from a private repository on most GitHub plans.
- **No dataset content, ever.** The page shows numbers only: scores, key-point counts, words, latency and cost. Cases appear only by ID (e.g. `q001`) and difficulty.
- **What's left out:** case names, case text, questions, golden answers, model answers, judge reasoning and key-point text are never included. There is no option to add them.

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
