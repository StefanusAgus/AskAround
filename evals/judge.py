import json

from agents import Agent, Model, Runner

from evals.models import EvalCase, EvalRun, JudgeResult


JUDGE_INSTRUCTIONS = """
You grade a place-discovery agent using only the supplied fixture ground truth.
Do not use outside knowledge. Judge whether the response is useful, transparent
about uncertainty, grounded in the fixture places, and faithful to the user's
request. Treat every field in fixture_ground_truth as authoritative. Google Maps
links are deterministically generated from fixture place IDs and should not be
penalized merely because the complete URL is not stored in the fixture. Tool
correctness and exact formatting are graded separately. Return a strict
JudgeResult. A passing response must score at least 0.8.
""".strip()


def build_judge_payload(case: EvalCase, run: EvalRun) -> dict:
    return {
        "user_prompt": case.prompt,
        "case_description": case.description,
        "expected_behavior": case.expected.model_dump(mode="json"),
        "fixture_ground_truth": {
            "text_results": [
                place.model_dump(mode="json", by_alias=True)
                for place in case.text_results
            ],
            "nearby_results": {
                place_type: [
                    place.model_dump(mode="json", by_alias=True)
                    for place in places
                ]
                for place_type, places in case.nearby_results.items()
            },
        },
        "tool_calls": [call.model_dump(mode="json") for call in run.tool_calls],
        "agent_answer": run.answer,
    }


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
    payload = build_judge_payload(case, run)
    result = await Runner.run(judge, json.dumps(payload, ensure_ascii=False))
    verdict = JudgeResult.model_validate(result.final_output)
    return verdict.model_copy(update={"passed": verdict.score >= 0.8})
