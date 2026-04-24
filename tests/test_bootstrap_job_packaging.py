from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_cloud_run_job_packaging_files_exist() -> None:
    dockerfile = ROOT / "bootstrap" / "Dockerfile"
    cloudbuild = ROOT / "infra" / "cloudbuild" / "bootstrap-job.yaml"
    entrypoint = ROOT / "bootstrap" / "src" / "zeler_bootstrap" / "__main__.py"

    assert dockerfile.exists()
    assert cloudbuild.exists()
    assert entrypoint.exists()

    assert "zeler_bootstrap" in dockerfile.read_text(encoding="utf-8")
    assert "gcloud run jobs deploy zeler-bootstrap" in cloudbuild.read_text(encoding="utf-8")
