# AskAround agent evaluations

This folder contains a small, repeatable evaluation suite for the AskAround
agent. The configured OpenRouter model runs the real agent workflow, while
Google Places is replaced with local fixtures from `cases.json`. Running an
evaluation therefore uses model tokens but does not make billable Google Maps
API requests.

## What is evaluated

The representative cases cover:

- resolving a postcode before searching nearby;
- handling multiple itinerary categories from one location;
- choosing a valid broader place type for a dish such as nasi lemak;
- returning three ranked recommendations by default;
- providing ratings, addresses, prices, hours, and valid Maps links; and
- stopping safely when a location cannot be found.

Deterministic graders inspect tool order, parameters, resolved coordinates,
region codes, place types, grounding, recommendation count, rating order,
links, required details, duplicates, and location-not-found behavior. An
optional LLM judge evaluates usefulness and transparent uncertainty.

## Prerequisites

From the repository root, install the Python 3.14 environment:

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD '.uv-python'
uv sync
```

Copy `.env.example` to `.env` and configure at least:

```dotenv
OPENROUTER_API_KEY=your-openrouter-api-key
OPENROUTER_MODEL=openai/gpt-5.6-luna
```

The target model is read from `OPENROUTER_MODEL`. The Google Maps API key is
not required for evaluations because all place data is fixture-backed.

## Run the evaluations

Run all cases with deterministic graders:

```powershell
uv run python -m evals.runner
```

Run one case:

```powershell
uv run python -m evals.runner --case location_not_found
```

Repeat `--case` to run a selected group:

```powershell
uv run python -m evals.runner `
  --case library_near_postcode `
  --case hotpot_default_top_three
```

Available case IDs are:

- `library_near_postcode`
- `multi_stop_suntec`
- `nasi_lemak_type_reasoning`
- `hotpot_default_top_three`
- `location_not_found`

## Enable the LLM judge

Set a judge model in `.env`:

```dotenv
EVAL_JUDGE_MODEL=openai/gpt-5.6-luna
```

Then run:

```powershell
uv run python -m evals.runner --judge
```

The LLM judge adds one model call per successfully completed case and therefore
increases OpenRouter usage. Its passing threshold is `0.8`. Deterministic
grader failures still fail the case even when the LLM judge passes it.

## Reports and exit codes

The default JSON report is written to:

```text
evals/results/latest.json
```

Choose another destination with:

```powershell
uv run python -m evals.runner --output evals/results/my-run.json
```

Reports include the final answer, recorded tool calls, every deterministic
grade and explanation, the deterministic score, and the optional judge result.
The command exits with code `0` only when every selected case passes; otherwise
it exits with code `1`, making it suitable for CI.

Generated reports are ignored by Git because model behavior can vary between
runs and reports may contain full prompts and outputs.

## Offline software tests

The evaluation framework itself has offline tests. These do not call OpenRouter
or Google Places:

```powershell
uv run pytest tests/test_evals.py tests/test_validation.py
```

Run the complete software test suite with:

```powershell
uv run pytest
```

## Adding a case

Add a validated entry to `cases.json` containing:

1. the user prompt;
2. Text Search fixture results;
3. Nearby Search fixture results keyed by supported Google place type; and
4. the expected tool behavior and response requirements.

Keep cases small and focused on one behavior. Prefer deterministic graders for
facts that can be checked in code, and reserve the LLM judge for qualitative
properties such as usefulness and communication of uncertainty.

## Troubleshooting

- `OPENROUTER_API_KEY is not set`: add the key to `.env` in the repository root.
- `Unknown evaluation case`: check the case ID against the list above.
- A tool-workflow grade fails: inspect `run.tool_calls` in the JSON report.
- A grounding grade fails: compare the numbered recommendations with the place
  names provided in the case fixtures.
- A Maps-link or detail grade fails: inspect the final Markdown response in
  `run.answer`.
