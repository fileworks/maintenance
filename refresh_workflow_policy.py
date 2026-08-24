"""Render MediaSorter's exact workflow policy from the maintenance model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maintenance.workflows import media_sorter_workflow_policy

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "media-sorter" / "contracts" / "workflow-policy.json"


def rendered() -> str:
    return json.dumps(media_sorter_workflow_policy(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    expected = rendered()
    if args.check:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != expected:
            print(f"{TARGET} is stale; run python -m maintenance.refresh_workflow_policy")
            return 1
        print(f"{TARGET} matches canonical workflow policy")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(expected, encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
