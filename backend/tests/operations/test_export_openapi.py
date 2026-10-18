import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "scripts" / "export_openapi.py"


def export(
    *arguments: str | Path, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(EXPORTER), *map(str, arguments)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_export_is_deterministic_and_runs_without_database(tmp_path: Path) -> None:
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    env = {
        **os.environ,
        "ROOMBOOK_DATABASE_URL": "postgresql+psycopg://nobody:private@127.0.0.1:1/offline",
        "ROOMBOOK_VERSION": "runtime-version",
    }
    result = export("--output", first, env=env)
    assert result.returncode == 0, result.stderr
    assert export("--output", second).returncode == 0
    assert first.read_bytes() == second.read_bytes()
    schema = json.loads(first.read_text())
    assert "/health" in schema["paths"]
    assert "private" not in first.read_text()
    assert "runtime-version" not in first.read_text()


def test_check_detects_drift_without_rewriting_file(tmp_path: Path) -> None:
    target = tmp_path / "schema.json"
    assert export("--output", target).returncode == 0
    assert export("--check", "--output", target).returncode == 0
    target.write_text('{"different": true}\n', encoding="utf-8")
    before = target.read_bytes()
    result = export("--check", "--output", target)
    assert result.returncode == 1
    assert "differs" in result.stderr
    assert target.read_bytes() == before


def test_check_missing_export_does_not_create_it(tmp_path: Path) -> None:
    target = tmp_path / "missing.json"
    result = export("--check", "--output", target)
    assert result.returncode == 1
    assert "missing" in result.stderr
    assert not target.exists()
