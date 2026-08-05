from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md",
    "LICENSE",
    "Dockerfile",
    "docker-compose.yml",
    "render.yaml",
    ".env.example",
    "requirements.txt",
    "pyproject.toml",
    "tide_mem/api.py",
    "tide_mem/models.py",
    "docs/METHOD.md",
    "docs/DEPLOYMENT.md",
    "docs/ACCOUNT_HANDOFF.md",
    "docs/SECURITY_AND_DATA.md",
    "docs/SUBMISSION_APPLICATION_ZH.md",
    "SUBMISSION_NOTES.txt",
    "PUBLISH_TO_GITHUB.cmd",
    "VERIFY_AND_PREPARE_SUBMISSION.cmd",
    "scripts/publish_github.ps1",
    "scripts/verify_hosted.ps1",
    "scripts/build_application.py",
    "scripts/smoke_test.py",
    "deploy/docker-entrypoint.sh",
    ".github/workflows/ci.yml",
    ".github/workflows/container.yml",
    ".github/workflows/hosted-health.yml",
]
PUBLIC_TEMPLATE_FILES = {
    Path("docs/SUBMISSION_APPLICATION_ZH.md"),
    Path("SUBMISSION_NOTES.txt"),
    Path("CITATION.cff.template"),
}
PLACEHOLDER_LITERAL_FILES = {
    Path("scripts/build_application.py"),
    Path("tests/test_build_application.py"),
}
PRIVATE_READY_FILES = [
    ROOT / "submission-private/SUBMISSION_APPLICATION_READY.md",
    ROOT / "submission-private/SUBMISSION_NOTES_READY.txt",
]
TEXT_SUFFIXES = {".py", ".ps1", ".cmd", ".sh", ".md", ".txt", ".toml", ".yml", ".yaml", ".example", ""}
SECRET_PATTERNS = {
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "GitHub classic/OAuth token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "GitHub fine-grained token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
}
PLACEHOLDER_RE = re.compile(r"\[(?:YOUR |PUBLIC |HTTPS |FULL |IMAGE |TEAM )[A-Z0-9 _/;.-]+\]")


def git_tracked() -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [path.relative_to(ROOT) for path in ROOT.rglob("*") if path.is_file()]
    return [Path(line) for line in output.splitlines() if line.strip()]


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Check repository readiness without exposing secrets")
    parser.add_argument(
        "--strict-placeholders",
        action="store_true",
        help="also require generated private application files with no unresolved placeholders",
    )
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required file: {relative}")

    tracked = git_tracked()
    forbidden_names = {
        ".env",
        "tide_mem.sqlite3",
        "eval_key.txt",
        "memory_system_key.txt",
        "github-metadata.json",
    }
    for relative in tracked:
        if relative.name in forbidden_names or relative.suffix in {".sqlite3", ".db"}:
            errors.append(f"sensitive/runtime artifact appears tracked: {relative}")

    template_placeholder_hits: list[str] = []
    unexpected_placeholder_hits: list[str] = []
    for relative in tracked:
        path = ROOT / relative
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = read_text(path)
        if text is None:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"possible {label} in {relative}")
        if PLACEHOLDER_RE.search(text):
            if relative in PUBLIC_TEMPLATE_FILES:
                template_placeholder_hits.append(str(relative))
            elif relative not in PLACEHOLDER_LITERAL_FILES:
                unexpected_placeholder_hits.append(str(relative))

    if unexpected_placeholder_hits:
        errors.append(
            "unexpected application placeholders remain outside public templates: "
            + ", ".join(sorted(set(unexpected_placeholder_hits)))
        )
    if template_placeholder_hits:
        warnings.append(
            "public reusable templates intentionally retain placeholders: "
            + ", ".join(sorted(set(template_placeholder_hits)))
        )

    version_checks = {
        "README version": (ROOT / "README.md", "0.1.0-amc2026"),
        "runtime version": (ROOT / "tide_mem/config.py", 'version="0.1.0-amc2026"'),
        "compose image": (ROOT / "docker-compose.yml", "tide-mem:0.1.0-amc2026"),
        "release tag in Render/application tooling": (ROOT / "scripts/build_application.py", "v0.1.0-amc2026"),
    }
    for label, (path, needle) in version_checks.items():
        if path.is_file() and needle not in path.read_text(encoding="utf-8"):
            errors.append(f"{label} is inconsistent")

    if args.strict_placeholders:
        for path in PRIVATE_READY_FILES:
            if not path.is_file():
                errors.append(f"missing generated private application file: {path.relative_to(ROOT)}")
                continue
            text = path.read_text(encoding="utf-8")
            if PLACEHOLDER_RE.search(text) or "[填写你同意公开的范围]" in text:
                errors.append(f"unresolved placeholder remains in {path.relative_to(ROOT)}")
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    errors.append(f"possible {label} in private application file {path.relative_to(ROOT)}")

    if errors:
        print("SUBMISSION CHECK: FAIL", file=sys.stderr)
        for error in errors:
            print(f"  ERROR: {error}", file=sys.stderr)
        for warning in warnings:
            print(f"  WARNING: {warning}", file=sys.stderr)
        return 1

    print("SUBMISSION CHECK: PASS")
    for warning in warnings:
        print(f"  WARNING: {warning}")
    print(f"  checked_files={len(tracked)}")
    print("  no tracked runtime database or recognized secret pattern found")
    if args.strict_placeholders:
        print("  generated private application files contain no unresolved placeholders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
