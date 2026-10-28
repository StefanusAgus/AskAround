import json
from pathlib import Path

from pydantic import TypeAdapter

from evals.models import EvalCase


DATASET_PATH = Path(__file__).with_name("cases.json")


def load_eval_cases(path: Path = DATASET_PATH) -> list[EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = TypeAdapter(list[EvalCase]).validate_python(payload)
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Evaluation case IDs must be unique")
    return cases
