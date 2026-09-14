"""Exercise deployment control flow with stubbed Docker/HTTP, never a remote host."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure", [None, "FAIL_MIGRATION", "FAIL_START", "FAIL_HEALTH"])
def test_deploy_preserves_old_app_or_rolls_back(tmp_path, failure):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    scripts = {
        "docker": """#!/bin/bash
printf '%s\\n' "$*" >> "$COMMAND_LOG"
case "$*" in
  *" transfercar migrate") [[ "${FAIL_MIGRATION:-0}" != 1 ]] || exit 1 ;;
  "run -d "*) [[ "${FAIL_START:-0}" != 1 ]] || exit 1 ;;
esac
exit 0
""",
        "curl": '#!/bin/bash\n[[ "${FAIL_HEALTH:-0}" != 1 ]]\n',
        "sleep": "#!/bin/bash\nexit 0\n",
    }
    for name, text in scripts.items():
        path = binaries / name
        path.write_text(text)
        path.chmod(0o755)
    for name in ("app.env", "migration.env"):
        (tmp_path / name).write_text("DATABASE_URL=stubbed\n")
    log = tmp_path / "commands.log"
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "DEPLOY_DIR": str(tmp_path),
        "COMMAND_LOG": str(log),
    }
    if failure:
        env[failure] = "1"
    script = Path(__file__).resolve().parents[1] / "deploy/deploy.sh"
    result = subprocess.run(
        ["bash", str(script), "ghcr.io/example/transfercar:" + "a" * 40],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    commands = log.read_text()
    if failure == "FAIL_MIGRATION":
        assert result.returncode != 0
        assert "stop transfercar-dashboard" not in commands
    elif failure:
        assert result.returncode != 0
        assert "start transfercar-dashboard" in commands
        assert "rm -f transfercar-dashboard" in commands
    else:
        assert result.returncode == 0, result.stderr
        assert "rm transfercar-dashboard-rollback-" in commands
