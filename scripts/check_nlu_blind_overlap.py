"""Fail when a blind test utterance appears verbatim in training data."""
from pathlib import Path
import re
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def examples(path: Path):
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for item in document.get("nlu", []):
        if "intent" not in item:
            continue
        for line in str(item.get("examples", "")).splitlines():
            line = line.strip()
            if line.startswith("- "):
                yield re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", line[2:]).strip()


blind = set(examples(ROOT / "tests" / "nlu_blind_round3.yml"))
training = set()
for path in (ROOT / "data").glob("*.yml"):
    training.update(examples(path))
overlap = sorted(blind & training)
print(f"blind={len(blind)} training={len(training)} exact_overlap={len(overlap)}")
if overlap:
    print("\n".join(overlap))
    sys.exit(1)
