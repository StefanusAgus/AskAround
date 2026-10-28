import re
from collections import Counter
from urllib.parse import urlparse

from app.constants import GOOGLE_PLACE_FILTER_TYPES
from evals.models import EvalCase, EvalRun, GradeResult


RECOMMENDATION_PATTERN = re.compile(
    r"^\s*\d+\.\s+\*\*(.+?)\*\*",
    flags=re.MULTILINE,
)
MAPS_LINK_PATTERN = re.compile(
    r"\[View on Google Maps\]\((https://[^\s)]+)\)"
)


def _grade(name: str, passed: bool, detail: str) -> GradeResult:
    return GradeResult(
        name=name,
        passed=passed,
        score=1.0 if passed else 0.0,
        detail=detail,
    )


def _grade_tool_workflow(case: EvalCase, run: EvalRun) -> GradeResult:
    calls = run.tool_calls
    expected_nearby_count = len(case.expected.nearby_type_options)
    expected_count = 1 + expected_nearby_count
    sequence_valid = (
        len(calls) == expected_count
        and calls[0].tool == "search_google_places_text"
        and all(
            call.tool == "search_google_places_nearby" for call in calls[1:]
        )
    )
    return _grade(
        "tool_workflow",
        sequence_valid,
        f"Expected Text Search followed by {expected_nearby_count} Nearby "
        f"Search call(s); received {[call.tool for call in calls]}",
    )


def _grade_location_query(case: EvalCase, run: EvalRun) -> GradeResult:
    if not run.tool_calls:
        return _grade("location_query", False, "Text Search was not called")
    query = str(run.tool_calls[0].parameters.get("query", "")).lower()
    missing = [
        fragment
        for fragment in case.expected.location_query_contains
        if fragment.lower() not in query
    ]
    return _grade(
        "location_query",
        not missing,
        "Location query contains all required fragments"
        if not missing
        else f"Missing query fragments: {missing}",
    )


def _grade_nearby_types(case: EvalCase, run: EvalRun) -> GradeResult:
    actual_types = []
    for call in run.tool_calls:
        if call.tool == "search_google_places_nearby":
            actual_types.extend(call.parameters.get("included_types", []))

    remaining = list(actual_types)
    missing_groups = []
    for options in case.expected.nearby_type_options:
        match = next((value for value in remaining if value in options), None)
        if match is None:
            missing_groups.append(options)
        else:
            remaining.remove(match)

    invalid = sorted(set(actual_types) - GOOGLE_PLACE_FILTER_TYPES)
    forbidden = sorted(set(actual_types) & set(case.expected.forbidden_types))
    passed = not missing_groups and not remaining and not invalid and not forbidden
    return _grade(
        "nearby_types",
        passed,
        f"actual={actual_types}, missing_options={missing_groups}, "
        f"unexpected={remaining}, invalid={invalid}, forbidden={forbidden}",
    )


def _grade_region(case: EvalCase, run: EvalRun) -> GradeResult:
    actual = [
        call.parameters.get("region_code")
        for call in run.tool_calls
        if "region_code" in call.parameters
    ]
    passed = bool(actual) and all(
        region == case.expected.region_code for region in actual
    )
    return _grade(
        "region",
        passed,
        f"Expected {case.expected.region_code}; received {actual}",
    )


def _grade_coordinates(case: EvalCase, run: EvalRun) -> GradeResult:
    nearby_calls = [
        call for call in run.tool_calls if call.tool == "search_google_places_nearby"
    ]
    if not nearby_calls:
        passed = not case.expected.nearby_type_options
        return _grade(
            "resolved_coordinates",
            passed,
            "No Nearby Search expected" if passed else "Nearby Search was not called",
        )
    anchor = case.text_results[0].location if case.text_results else None
    if anchor is None:
        return _grade(
            "resolved_coordinates",
            False,
            "Ground-truth anchor has no coordinates",
        )
    passed = all(
        abs(float(call.parameters.get("latitude", 999)) - anchor.latitude) < 1e-7
        and abs(float(call.parameters.get("longitude", 999)) - anchor.longitude)
        < 1e-7
        for call in nearby_calls
    )
    return _grade(
        "resolved_coordinates",
        passed,
        "Nearby Search reused the resolved anchor coordinates"
        if passed
        else "Nearby Search did not use the fixture anchor coordinates",
    )
def _known_places(case: EvalCase) -> dict[str, float | None]:
    return {
        place.display_name.text: place.rating
        for places in case.nearby_results.values()
        for place in places
        if place.display_name
    }


def _grade_grounding(case: EvalCase, run: EvalRun) -> GradeResult:
    recommendations = RECOMMENDATION_PATTERN.findall(run.answer)
    known = _known_places(case)
    unknown = [name for name in recommendations if name not in known]
    expected_count = case.expected.expected_recommendations
    count_matches = len(recommendations) == expected_count
    passed = count_matches and not unknown
    return _grade(
        "grounded_recommendations",
        passed,
        f"recommendations={recommendations}, unknown={unknown}, "
        f"expected_count={expected_count}",
    )


def _grade_ranking(case: EvalCase, run: EvalRun) -> GradeResult:
    if not case.expected.require_ranked_results:
        return _grade("rating_order", True, "Ranking not required for this case")

    failures = []
    for place_type, places in case.nearby_results.items():
        expected_names = [
            place.display_name.text
            for place in sorted(
                places,
                key=lambda place: (
                    place.rating is not None,
                    place.rating or 0,
                    place.user_rating_count or 0,
                ),
                reverse=True,
            )
            if place.display_name and place.display_name.text in run.answer
        ]
        positions = [run.answer.index(name) for name in expected_names]
        if positions != sorted(positions):
            failures.append(place_type)

    return _grade(
        "rating_order",
        not failures,
        "Results are ordered by rating and review count"
        if not failures
        else f"Incorrect ordering for: {failures}",
    )


def _grade_maps_links(case: EvalCase, run: EvalRun) -> GradeResult:
    recommendation_count = len(RECOMMENDATION_PATTERN.findall(run.answer))
    links = MAPS_LINK_PATTERN.findall(run.answer)
    valid = all(
        urlparse(url).scheme == "https"
        and urlparse(url).netloc == "www.google.com"
        and urlparse(url).path.startswith("/maps/")
        for url in links
    )
    expected_count = 0 if case.expected.location_not_found else recommendation_count
    passed = valid and len(links) == expected_count
    return _grade(
        "maps_links",
        passed,
        f"Expected {expected_count} valid Maps links; received {len(links)}",
    )


def _grade_restaurant_details(case: EvalCase, run: EvalRun) -> GradeResult:
    if not case.expected.require_restaurant_details:
        return _grade(
            "restaurant_details",
            True,
            "Restaurant details not required for this case",
        )
    count = len(RECOMMENDATION_PATTERN.findall(run.answer))
    price_count = len(re.findall(r"(?im)^\s*-?\s*price\s*:", run.answer))
    passed = price_count >= count
    return _grade(
        "restaurant_details",
        passed,
        f"recommendations={count}, price_fields={price_count}",
    )


def _grade_recommendation_details(case: EvalCase, run: EvalRun) -> GradeResult:
    count = len(RECOMMENDATION_PATTERN.findall(run.answer))
    if count == 0:
        return _grade(
            "recommendation_details",
            case.expected.expected_recommendations == 0,
            "No recommendation details expected",
        )
    rating_count = len(re.findall(r"(?im)^\s*-?\s*rating\s*:", run.answer))
    address_count = len(re.findall(r"(?im)^\s*-?\s*address\s*:", run.answer))
    hours_count = len(re.findall(r"(?im)^\s*-?\s*.+hours\s*:", run.answer))
    hours_valid = (
        not case.expected.require_opening_hours or hours_count >= count
    )
    passed = rating_count >= count and address_count >= count and hours_valid
    return _grade(
        "recommendation_details",
        passed,
        f"recommendations={count}, ratings={rating_count}, "
        f"addresses={address_count}, hours={hours_count}",
    )


def _grade_location_failure(case: EvalCase, run: EvalRun) -> GradeResult:
    if not case.expected.location_not_found:
        return _grade(
            "location_not_found",
            True,
            "Location failure behavior not required for this case",
        )
    nearby_calls = [
        call for call in run.tool_calls if call.tool == "search_google_places_nearby"
    ]
    failure_language = any(
        phrase in run.answer.lower()
        for phrase in ("not found", "no match", "could not", "couldn't", "unable")
    )
    passed = not nearby_calls and failure_language
    return _grade(
        "location_not_found",
        passed,
        "No Nearby Search was made and the response explains the failure"
        if passed
        else "Expected no Nearby Search and a clear location failure message",
    )


def grade_run(case: EvalCase, run: EvalRun) -> list[GradeResult]:
    if run.error:
        return [
            _grade(
                "run_completed",
                False,
                f"Agent run failed: {run.error}",
            )
        ]

    grades = [
        _grade_tool_workflow(case, run),
        _grade_location_query(case, run),
        _grade_nearby_types(case, run),
        _grade_region(case, run),
        _grade_coordinates(case, run),
        _grade_grounding(case, run),
        _grade_ranking(case, run),
        _grade_maps_links(case, run),
        _grade_restaurant_details(case, run),
        _grade_recommendation_details(case, run),
        _grade_location_failure(case, run),
    ]
    duplicate_names = [
        name
        for name, count in Counter(RECOMMENDATION_PATTERN.findall(run.answer)).items()
        if count > 1
    ]
    grades.append(
        _grade(
            "no_duplicate_recommendations",
            not duplicate_names,
            "No duplicate recommendations"
            if not duplicate_names
            else f"Duplicate recommendations: {duplicate_names}",
        )
    )
    return grades
