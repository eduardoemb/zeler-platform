from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "infra" / "docker" / "gen_mongo_keyfile.sh"


def _executable(name: str) -> str:
    path = shutil.which(name)
    assert path is not None, f"{name} must be available"
    return path


def test_gitignore_excludes_generated_mongo_keyfile() -> None:
    result = subprocess.run(  # noqa: S603 - test executes the local git binary.
        [_executable("git"), "check-ignore", "infra/docker/mongo-keyfiles/rs0.key"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "infra/docker/mongo-keyfiles/rs0.key"


def test_gen_mongo_keyfile_creates_400_keyfile_and_is_idempotent(tmp_path: Path) -> None:
    docker_dir = tmp_path / "infra" / "docker"
    docker_dir.mkdir(parents=True)
    script_copy = docker_dir / "gen_mongo_keyfile.sh"
    shutil.copy2(SCRIPT_PATH, script_copy)

    first_run = subprocess.run(  # noqa: S603 - test executes the local script contract.
        [_executable("bash"), str(script_copy)],
        check=False,
        capture_output=True,
        text=True,
    )

    keyfile = docker_dir / "mongo-keyfiles" / "rs0.key"
    assert first_run.returncode == 0, first_run.stderr
    assert keyfile.exists()
    assert stat.S_IMODE(keyfile.stat().st_mode) == 0o400
    assert keyfile.read_text(encoding="utf-8").strip()

    original_content = keyfile.read_text(encoding="utf-8")
    second_run = subprocess.run(  # noqa: S603 - test executes the local script contract.
        [_executable("bash"), str(script_copy)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert second_run.returncode == 0, second_run.stderr
    assert "keyfile already exists" in second_run.stderr
    assert keyfile.read_text(encoding="utf-8") == original_content
