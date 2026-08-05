from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import build_application


def test_application_generator_produces_ready_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    argv = [
        "build_application.py",
        "--name",
        "Example Researcher",
        "--email",
        "researcher@example.org",
        "--affiliation",
        "Example Lab",
        "--team",
        "Solo participant",
        "--repo-url",
        "https://github.com/example/tide-mem",
        "--base-url",
        "https://tide-example.onrender.com",
        "--commit-sha",
        "0123456789abcdef0123456789abcdef01234567",
        "--image-digest",
        "ghcr.io/example/tide-mem:v0.1.0-amc2026",
        "--output-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr("sys.argv", argv)

    assert build_application.main() == 0

    application = (tmp_path / "SUBMISSION_APPLICATION_READY.md").read_text(encoding="utf-8")
    notes = (tmp_path / "SUBMISSION_NOTES_READY.txt").read_text(encoding="utf-8")
    metadata = json.loads((tmp_path / "submission-metadata.json").read_text(encoding="utf-8"))

    assert "[YOUR NAME]" not in application
    assert "[HTTPS PUBLIC BASE URL]" not in notes
    assert "researcher@example.org" in application
    assert metadata["commit_sha"] == "0123456789abcdef0123456789abcdef01234567"
    assert metadata["contains_secrets"] is False


@pytest.mark.parametrize(
    ("value", "validator"),
    [
        ("http://github.com/example/tide-mem", build_application.normalize_repo_url),
        ("https://example.org/path", build_application.normalize_base_url),
        ("not-a-commit", build_application.validate_sha),
        ("not-an-email", build_application.validate_email),
    ],
)
def test_application_generator_rejects_invalid_identity_fields(value: str, validator) -> None:
    with pytest.raises(ValueError):
        validator(value)
