"""Validate cron execution with a minimal environment and an offline collector stub."""

import fcntl
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def daily_task(tmp_path):
    project = tmp_path / "project with spaces"
    for directory in ("scripts", ".local", ".venv/bin", "transfercar", "test-bin"):
        (project / directory).mkdir(parents=True)
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "scripts/collect_daily.sh",
        project / "scripts/collect_daily.sh",
    )
    (project / ".venv/bin/python").symlink_to(Path(sys.executable).resolve())
    (project / "transfercar/__init__.py").touch()
    (project / "transfercar/cli.py").write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "assert sys.argv[1:3] == ['collect', '--run-id']\n"
        "assert os.environ['DATABASE_URL'] == 'private-test-credential'\n"
        "assert 'SUPABASE_ADMIN_DATABASE_URL' not in os.environ\n"
        "with Path('.local/invocations.jsonl').open('a') as out:\n"
        "    out.write(json.dumps({'run_id': sys.argv[3]}) + '\\n')\n"
        "print('Collector stub ran')\n"
        "sys.exit(int(os.environ.get('STUB_EXIT_CODE', '0')))\n"
    )
    (project / ".local/supabase-runtime.env").write_text(
        "DATABASE_URL='private-test-credential'\n"
        "SUPABASE_ADMIN_DATABASE_URL='unused-admin-credential'\n"
    )
    # Freeze the date and test its mapping without depending on wall-clock midnight.
    date = project / "test-bin/date"
    date.write_text('#!/bin/sh\nprintf "%s\\n" "${STUB_DAY:-2026-09-17}"\n')
    date.chmod(0o755)
    env = {"PATH": f"{project / 'test-bin'}:/usr/bin:/bin"}

    def run(**extra):
        return subprocess.run(
            ["/bin/bash", str(project / "scripts/collect_daily.sh")],
            cwd=tmp_path,
            env={**env, **extra},
            capture_output=True,
            text=True,
            timeout=15,
        )

    return project, run


def test_daily_task_loads_credentials_and_reuses_only_same_day_id(daily_task):
    project, run = daily_task
    assert run().returncode == 0
    assert run().returncode == 0
    assert run(STUB_DAY="2026-09-18").returncode == 0
    calls = [
        json.loads(line) for line in (project / ".local/invocations.jsonl").read_text().splitlines()
    ]
    assert calls[0]["run_id"] == calls[1]["run_id"]
    assert calls[2]["run_id"] != calls[0]["run_id"]
    log = project / ".local/logs/collection/2026-09-17.log"
    assert "private-test-credential" not in log.read_text()
    assert "exit_code=0" in log.read_text()
    assert log.stat().st_mode & 0o777 == 0o600


def test_daily_task_skips_overlap(daily_task):
    project, run = daily_task
    with (project / ".local/collect-daily.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert run().returncode == 0
    assert not (project / ".local/invocations.jsonl").exists()
    assert (
        "another local collection"
        in (project / ".local/logs/collection/2026-09-17.log").read_text()
    )


def test_daily_task_preserves_failure_exit_code(daily_task):
    project, run = daily_task
    result = run(STUB_EXIT_CODE="7")
    assert result.returncode == 7
    assert "exit_code=7" in (project / ".local/logs/collection/2026-09-17.log").read_text()


@pytest.mark.parametrize("config_exists", [False, True])
def test_daily_task_refuses_missing_config_even_with_inherited_url(daily_task, config_exists):
    project, run = daily_task
    config = project / ".local/supabase-runtime.env"
    if config_exists:
        config.write_text("# DATABASE_URL has not been configured\n")
    else:
        config.unlink()
    assert run(DATABASE_URL="inherited-connection").returncode == 1
    assert not (project / ".local/invocations.jsonl").exists()
