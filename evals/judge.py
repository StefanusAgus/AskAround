import json

from agents import Agent, Model, Runner

from evals.models import EvalCase, EvalRun, JudgeResult


JUDGE_INSTRUCTIONS = """
You grade a place-discovery agent using only the supplied fixture ground truth.
Do not use outside knowledge. Judge whether the response is useful, transparent
about uncertainty, grounded in the fixture places, and faithful to the user's
request. Tool correctness and exact formatting are graded separately. Return a
strict JudgeResult. A passing response must score at least 0.8.
""".strip()


async def judge_run(
    case: EvalCase,
    run: EvalRun,
    model: Model,
) -> JudgeResult:
    judge = Agent(
        name="AskAround Eval Judge",
        instructions=JUDGE_INSTRUCTIONS,
        model=model,
        output_type=JudgeResult,
    )
    fixture_names = sorted(
        {
            place.display_name.text
            for places in case.nearby_results.values()
            for place in places
            if place.display_name
        }
    )
    payload = {
        "user_prompt": case.prompt,
        "case_description": case.description,
        "expected_behavior": case.expected.model_dump(mode="json"),
        "fixture_place_names": fixture_names,
        "tool_calls": [call.model_dump(mode="json") for call in run.tool_calls],
        "agent_answer": run.answer,
    }
    result = await Runner.run(judge, json.dumps(payload, ensure_ascii=False))
    verdict = JudgeResult.model_validate(result.final_output)
    return verdict.model_copy(update={"passed": verdict.score >= 0.8})
