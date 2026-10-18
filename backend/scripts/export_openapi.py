"""Export the implemented API schema without opening a database connection."""

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def schema_text() -> str:
    # Runtime environment and credentials must not change a committed API schema.
    settings = Settings(
        _env_file=None,
        database_url=None,
        environment="schema-export",
        version=Settings.model_fields["version"].default,
        commit_sha="unknown",
    )
    return json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail on schema drift")
    parser.add_argument("--output", type=Path, default=BACKEND_ROOT / "openapi.json")
    args = parser.parse_args()
    expected = schema_text()
    if args.check:
        try:
            actual = args.output.read_text(encoding="utf-8")
        except FileNotFoundError:
            print("OpenAPI export is missing. Run the export command first.", file=sys.stderr)
            return 1
        if actual != expected:
            print("OpenAPI export differs from the implemented API.", file=sys.stderr)
            return 1
        print("OpenAPI export matches the implemented API.")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8", newline="\n")
    print(f"Exported OpenAPI to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
