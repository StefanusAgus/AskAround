# AskAround evaluations

This folder contains a deliberately small agent-behavior evaluation suite.
Google Places is replaced by case-specific fixtures, while the configured
OpenRouter model runs the real agent workflow.

The deterministic graders check tool order and parameters, valid Google place
types, region selection, grounding, default result count, rating order, Maps
links, restaurant price and hours, duplicates, and location-not-found behavior.
An optional LLM judge grades usefulness and transparent handling of uncertainty.

Run all deterministic evaluations:

```powershell
uv run python -m evals.runner
```

Run one case and enable the LLM judge:

```powershell
uv run python -m evals.runner --case location_not_found --judge
```

The harness reads `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, and optionally
`EVAL_JUDGE_MODEL` from `.env`. JSON reports are written under `evals/results/`
and are intentionally ignored by Git.
