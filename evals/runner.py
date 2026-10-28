import argparse
import asyncio
import json
import os
from pathlib import Path

from agents import (
    Model,
    OpenAIChatCompletionsModel,
    Runner,
    set_tracing_disabled,
)
from openai import AsyncOpenAI

from app.agent.context import AgentContext
from app.agent.models import AgentAnswer
from app.agent.workflow import build_agent
from app.config import OpenRouterSettings
from app.constants import MAX_AGENT_TURNS, OPENROUTER_BASE_URL
from evals.dataset import load_eval_cases
from evals.fixtures import FixtureGooglePlacesService
from evals.graders import grade_run
from evals.judge import judge_run
from evals.models import EvalCase, EvalCaseResult, EvalReport, EvalRun, JudgeResult


set_tracing_disabled(True)


async def run_case(
    case: EvalCase,
    target_model: Model,
) -> EvalRun:
    google_places = FixtureGooglePlacesService(case)
    context = AgentContext(google_places=google_places)
    try:
        result = await Runner.run(
            build_agent(target_model),
            case.prompt,
            context=context,
            max_turns=MAX_AGENT_TURNS,
        )
        answer = AgentAnswer.model_validate(result.final_output).answer
        return EvalRun(
            case_id=case.id,
            answer=answer,
            tool_calls=google_places.tool_calls,
        )
    except Exception as exc:
        return EvalRun(
            case_id=case.id,
            tool_calls=google_places.tool_calls,
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_evaluations(
    settings: OpenRouterSettings,
    selected_case_ids: set[str] | None = None,
    use_judge: bool = False,
) -> EvalReport:
    cases = load_eval_cases()
    if selected_case_ids:
        cases = [case for case in cases if case.id in selected_case_ids]
        missing = selected_case_ids - {case.id for case in cases}
        if missing:
            raise ValueError(f"Unknown evaluation case(s): {sorted(missing)}")

    client = AsyncOpenAI(
        api_key=settings.api_key,
        base_url=OPENROUTER_BASE_URL,
        default_headers={"X-Title": "AskAround Evals"},
    )
    target_model = OpenAIChatCompletionsModel(
        model=settings.model,
        openai_client=client,
    )
    judge_model_name = os.getenv("EVAL_JUDGE_MODEL", "openai/gpt-5.6-luna")
    judge_model = OpenAIChatCompletionsModel(
        model=judge_model_name,
        openai_client=client,
    )

    case_results = []
    try:
        for case in cases:
            run = await run_case(case, target_model)
            grades = grade_run(case, run)
            deterministic_score = sum(grade.score for grade in grades) / len(grades)
            judge: JudgeResult | None = None
            if use_judge and not run.error:
                try:
                    judge = await judge_run(case, run, judge_model)
                except Exception as exc:
                    judge = JudgeResult(
                        passed=False,
                        score=0,
                        rationale=f"Judge failed: {type(exc).__name__}: {exc}",
                    )
            passed = all(grade.passed for grade in grades) and (
                judge is None or judge.passed
            )
            case_results.append(
                EvalCaseResult(
                    case_id=case.id,
                    passed=passed,
                    deterministic_score=deterministic_score,
                    grades=grades,
                    run=run,
                    judge=judge,
                )
            )
    finally:
        await client.close()

    passed_count = sum(result.passed for result in case_results)
    pass_rate = passed_count / len(case_results) if case_results else 0
    return EvalReport(
        model=settings.model,
        passed=passed_count == len(case_results),
        pass_rate=pass_rate,
        cases=case_results,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AskAround agent evaluations")
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run one case by ID. Repeat to select multiple cases.",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Also run the optional LLM-as-a-judge grader.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/results/latest.json"),
        help="JSON report destination.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    report = await run_evaluations(
        OpenRouterSettings.from_environment(),
        selected_case_ids=set(args.case_ids) if args.case_ids else None,
        use_judge=args.judge,
    )
    payload = report.model_dump_json(indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
