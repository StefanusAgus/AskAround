from types import SimpleNamespace

import pytest
from agents.testing import ScriptedModel

from app.agent.models import AgentAnswer
from app.models import PlaceSearchRequest
from evals.dataset import load_eval_cases
from evals.graders import grade_run
from evals.judge import build_judge_payload
from evals.models import EvalCaseResult, EvalReport, EvalRun, ToolCallRecord
from evals.runner import format_report_table, run_case


def _maps_link(place_id: str, name: str) -> str:
    return (
        "https://www.google.com/maps/search/"
        f"?api=1&query={name.replace(' ', '+')}&query_place_id={place_id}"
    )


def test_eval_dataset_is_small_valid_and_covers_edge_cases() -> None:
    cases = load_eval_cases()

    assert len(cases) == 5
    assert {case.id for case in cases} == {
        "library_near_postcode",
        "multi_stop_suntec",
        "nasi_lemak_type_reasoning",
        "hotpot_default_top_three",
        "location_not_found",
    }


def test_llm_judge_receives_complete_fixture_ground_truth() -> None:
    case = next(
        case
        for case in load_eval_cases()
        if case.id == "hotpot_default_top_three"
    )
    payload = build_judge_payload(
        case,
        EvalRun(case_id=case.id, answer="Fixture-backed answer"),
    )

    first_place = payload["fixture_ground_truth"]["nearby_results"][
        "hot_pot_restaurant"
    ][0]
    assert first_place["id"] == "hotpot-1"
    assert first_place["formattedAddress"] == "1 Tampines Central, Singapore"
    assert first_place["rating"] == 4.9
    assert first_place["userRatingCount"] == 1200
    assert first_place["priceRange"]["startPrice"]["currencyCode"] == "SGD"
    assert first_place["regularOpeningHours"]["openNow"] is True


def test_deterministic_graders_accept_grounded_ranked_restaurants() -> None:
    case = next(
        case
        for case in load_eval_cases()
        if case.id == "hotpot_default_top_three"
    )
    recommendations = [
        ("hotpot-1", "Tampines Hotpot One", "4.9"),
        ("hotpot-2", "Tampines Hotpot Two", "4.6"),
        ("hotpot-3", "Tampines Hotpot Three", "4.4"),
    ]
    answer_parts = ["### Top 3 hotpot near Tampines MRT"]
    for index, (place_id, name, rating) in enumerate(recommendations, start=1):
        answer_parts.extend(
            [
                f"{index}. **{name}**",
                f"- Rating: {rating}/5",
                "- Address: Tampines, Singapore",
                "- Price: SGD 20-40",
                "- Hours today: 11:00 AM-10:00 PM",
                f"- [View on Google Maps]({_maps_link(place_id, name)})",
            ]
        )
    run = EvalRun(
        case_id=case.id,
        answer="\n".join(answer_parts),
        tool_calls=[
            ToolCallRecord(
                tool="search_google_places_text",
                parameters={"query": "Tampines MRT Singapore", "region_code": "SG"},
            ),
            ToolCallRecord(
                tool="search_google_places_nearby",
                parameters={
                    "included_types": ["hot_pot_restaurant"],
                    "region_code": "SG",
                    "latitude": 1.3531,
                    "longitude": 103.9452,
                },
            ),
        ],
    )

    grades = grade_run(case, run)

    assert all(grade.passed for grade in grades), [
        grade.model_dump() for grade in grades if not grade.passed
    ]
    assert [grade.name for grade in grades] == [
        "task_completion",
        "tool_accuracy",
        "groundedness",
        "response_quality",
    ]

    report = EvalReport(
        model="test-model",
        passed=True,
        pass_rate=1,
        cases=[
            EvalCaseResult(
                case_id=case.id,
                passed=True,
                deterministic_score=1,
                grades=grades,
                run=run,
            )
        ],
    )
    table = format_report_table(report)
    assert "| Case" in table
    assert "| Task" in table
    assert "| Tools" in table
    assert "| Grounding" in table
    assert "| Response" in table
    assert "hotpot_default_top_three" in table
    assert "| TOTAL" in table
    assert "1/1 (100%)" in table
    assert "100% avg" in table
    assert "Overall: 1/1 cases passed (100%)" in table


def test_deterministic_graders_reject_hallucinated_place() -> None:
    case = next(
        case
        for case in load_eval_cases()
        if case.id == "library_near_postcode"
    )
    run = EvalRun(
        case_id=case.id,
        answer="1. **Invented Library**",
        tool_calls=[
            ToolCallRecord(
                tool="search_google_places_text",
                parameters={"query": "398371 Singapore", "region_code": "SG"},
            ),
            ToolCallRecord(
                tool="search_google_places_nearby",
                parameters={
                    "included_types": ["library"],
                    "region_code": "SG",
                    "latitude": 1.3118129,
                    "longitude": 103.886346,
                },
            ),
        ],
    )

    grades = {grade.name: grade for grade in grade_run(case, run)}

    assert grades["groundedness"].passed is False
    assert grades["response_quality"].passed is False


def test_location_not_found_grader_requires_no_nearby_call() -> None:
    case = next(
        case for case in load_eval_cases() if case.id == "location_not_found"
    )
    run = EvalRun(
        case_id=case.id,
        answer="I couldn’t find a matching location, so no nearby search was run.",
        tool_calls=[
            ToolCallRecord(
                tool="search_google_places_text",
                parameters={
                    "query": "Imaginary Place ZZZ999 Singapore",
                    "region_code": "SG",
                },
            )
        ],
    )

    assert all(grade.passed for grade in grade_run(case, run))


@pytest.mark.asyncio
async def test_eval_runner_uses_fixture_google_service(monkeypatch) -> None:
    case = next(
        case for case in load_eval_cases() if case.id == "location_not_found"
    )

    async def fake_runner_run(agent, prompt, context, max_turns):
        assert prompt == case.prompt
        assert max_turns > 0
        response = await context.google_places.search(
            PlaceSearchRequest(
                query="Imaginary Place ZZZ999 Singapore",
                region_code="SG",
            )
        )
        assert response.places == []
        return SimpleNamespace(
            final_output=AgentAnswer(
                answer="I could not find a matching location."
            )
        )

    monkeypatch.setattr("evals.runner.Runner.run", fake_runner_run)

    run = await run_case(case, ScriptedModel())

    assert run.error is None
    assert [call.tool for call in run.tool_calls] == [
        "search_google_places_text"
    ]
