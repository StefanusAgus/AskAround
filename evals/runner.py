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


METRIC_COLUMNS = (
    ("task_completion", "Task"),
    ("tool_accuracy", "Tools"),
    ("groundedness", "Grounding"),
    ("response_quality", "Response"),
)


def format_report_table(report: EvalReport) -> str:
    include_judge = any(result.judge is not None for result in report.cases)
    headers = ["Case", *(label for _, label in METRIC_COLUMNS), "Score"]
    if include_judge:
        headers.append("Judge")
    headers.append("Result")
    rows = []
    for result in report.cases:
        grades = {grade.name: grade for grade in result.grades}
        row = [
            result.case_id,
            *(
                "PASS" if grades[name].passed else "FAIL"
                for name, _ in METRIC_COLUMNS
            ),
            f"{result.deterministic_score:.0%}",
        ]
        if include_judge:
            row.append(
                "-"
                if result.judge is None
                else "PASS"
                if result.judge.passed
                else "FAIL"
            )
        row.append("PASS" if result.passed else "FAIL")
        rows.append(row)

    case_count = len(report.cases)

    def aggregate_cell(passed: int, total: int) -> str:
        percentage = passed / total if total else 0
        return f"{passed}/{total} ({percentage:.0%})"

    aggregate_row = ["TOTAL"]
    for metric_name, _ in METRIC_COLUMNS:
        metric_passes = sum(
            next(
                grade.passed
                for grade in result.grades
                if grade.name == metric_name
            )
            for result in report.cases
        )
        aggregate_row.append(aggregate_cell(metric_passes, case_count))
    average_score = (
        sum(result.deterministic_score for result in report.cases) / case_count
        if case_count
        else 0
    )
    aggregate_row.append(f"{average_score:.0%} avg")
    if include_judge:
        judged_results = [
            result.judge for result in report.cases if result.judge is not None
        ]
        aggregate_row.append(
            aggregate_cell(
                sum(judge.passed for judge in judged_results),
                len(judged_results),
            )
        )
    aggregate_row.append(
        aggregate_cell(sum(result.passed for result in report.cases), case_count)
    )
    rows.append(aggregate_row)

    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"

    def format_row(values: list[str]) -> str:
        return "| " + " | ".join(
            value.ljust(width) for value, width in zip(values, widths)
        ) + " |"

    lines = [
        "AskAround evaluation summary",
        separator,
        format_row(headers),
        separator,
        *(format_row(row) for row in rows[:-1]),
        separator,
        format_row(rows[-1]),
        separator,
        f"Overall: {sum(case.passed for case in report.cases)}/"
        f"{len(report.cases)} cases passed ({report.pass_rate:.0%})",
    ]
    return "\n".join(lines)


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
    print()
    print(format_report_table(report))
    print(f"JSON report: {args.output}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
