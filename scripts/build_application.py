from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
VERSION_TAG = "v0.1.0-amc2026"
APPLICATION_TEMPLATE = ROOT / "docs" / "SUBMISSION_APPLICATION_ZH.md"
NOTES_TEMPLATE = ROOT / "SUBMISSION_NOTES.txt"

PLACEHOLDER_RE = re.compile(r"\[(?:YOUR |PUBLIC |HTTPS |FULL |IMAGE |TEAM )[A-Z0-9 _/;.-]+\]")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SECRET_PATTERNS = {
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}\b"),
}


def one_line(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label} cannot be empty")
    if any(ch in value for ch in "\r\n"):
        raise ValueError(f"{label} must be a single line")
    for secret_label, pattern in SECRET_PATTERNS.items():
        if pattern.search(value):
            raise ValueError(f"{label} appears to contain a {secret_label}")
    return value


def normalize_repo_url(value: str) -> str:
    value = one_line(value, "repository URL").rstrip("/")
    parsed = urlparse(value)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"github.com", "www.github.com"}
        or len(parts) != 2
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("repository URL must be an HTTPS GitHub OWNER/REPOSITORY URL")
    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not owner or not repository:
        raise ValueError("repository URL must contain an owner and repository")
    return f"https://github.com/{owner}/{repository}"


def normalize_base_url(value: str) -> str:
    value = one_line(value, "base URL").rstrip("/")
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("base URL must be an HTTPS origin without a path, query, or credentials")
    return value


def validate_email(value: str) -> str:
    value = one_line(value, "email")
    if not EMAIL_RE.fullmatch(value):
        raise ValueError("email does not look valid")
    return value


def validate_sha(value: str) -> str:
    value = one_line(value, "commit SHA").lower()
    if not SHA_RE.fullmatch(value):
        raise ValueError("commit SHA must contain exactly 40 hexadecimal characters")
    return value


def render_template(template: str, replacements: dict[str, str], label: str) -> str:
    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    unresolved = sorted(set(PLACEHOLDER_RE.findall(rendered)))
    if "[填写你同意公开的范围]" in rendered:
        unresolved.append("[填写你同意公开的范围]")
    if unresolved:
        raise ValueError(f"{label} still has unresolved placeholders: {', '.join(unresolved)}")
    for secret_label, pattern in SECRET_PATTERNS.items():
        if pattern.search(rendered):
            raise ValueError(f"{label} appears to contain a {secret_label}")
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate private, ready-to-paste challenge application files without writing API keys"
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--affiliation", required=True)
    parser.add_argument("--team", required=True)
    parser.add_argument("--repo-url", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument(
        "--public-scope",
        default="联系人姓名、机构/团队、系统与公开仓库信息，以及经审核后的榜单成绩",
        help="Chinese text describing which contact/team fields may be shown publicly",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "submission-private",
    )
    args = parser.parse_args()

    name = one_line(args.name, "name")
    email = validate_email(args.email)
    affiliation = one_line(args.affiliation, "affiliation")
    team = one_line(args.team, "team")
    repo_url = normalize_repo_url(args.repo_url)
    base_url = normalize_base_url(args.base_url)
    commit_sha = validate_sha(args.commit_sha)
    image_digest = one_line(args.image_digest, "image identifier/digest")
    public_scope = one_line(args.public_scope, "public display scope")

    replacements = {
        "[YOUR NAME]": name,
        "[YOUR EMAIL]": email,
        "[YOUR AFFILIATION OR TEAM]": affiliation,
        "[TEAM MEMBERS; SOLO IF INDIVIDUAL]": team,
        "[PUBLIC GITHUB REPOSITORY URL]": repo_url,
        "[FULL 40-CHAR COMMIT SHA]": commit_sha,
        "[IMAGE ID OR DIGEST]": image_digest,
        "[HTTPS PUBLIC BASE URL]": base_url,
        "[填写你同意公开的范围]": public_scope,
    }

    application_template = APPLICATION_TEMPLATE.read_text(encoding="utf-8")
    application_template = application_template.replace(
        "> 提交前替换所有 `[方括号占位符]`。不要把 Eval Key、Leaderboard Key、Memory System Key 或模型供应商密钥写入此文件或 GitHub。",
        "> 本文件已由本地脚本填充非密钥字段。Eval Key、Leaderboard Key、Memory System Key 和模型供应商密钥均不应写入此文件或 GitHub。",
    ).replace(
        "[仅在赛事受控密钥字段中填写，不要粘贴到普通说明文本]",
        "仅在赛事受控密钥字段中填写（不写入本文件）",
    )
    application = render_template(
        application_template,
        replacements,
        "application",
    )
    notes = render_template(
        NOTES_TEMPLATE.read_text(encoding="utf-8"),
        replacements,
        "submission notes",
    )

    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = (ROOT / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    application_path = output_dir / "SUBMISSION_APPLICATION_READY.md"
    notes_path = output_dir / "SUBMISSION_NOTES_READY.txt"
    metadata_path = output_dir / "submission-metadata.json"

    application_path.write_text(application, encoding="utf-8")
    notes_path.write_text(notes, encoding="utf-8")
    metadata = {
        "system": "TIDE-Mem",
        "version": VERSION_TAG,
        "name": name,
        "email": email,
        "affiliation": affiliation,
        "team": team,
        "repository_url": repo_url,
        "commit_sha": commit_sha,
        "image_identifier": image_digest,
        "base_url": base_url,
        "add_url": f"{base_url}/v1/memory/add",
        "search_url": f"{base_url}/v1/memory/search",
        "health_url": f"{base_url}/health",
        "authentication": "X-Api-Key",
        "add_concurrency": 16,
        "search_concurrency": 16,
        "top_k": 100,
        "contains_secrets": False,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("APPLICATION GENERATION: PASS")
    print(f"  application={application_path}")
    print(f"  notes={notes_path}")
    print(f"  metadata={metadata_path}")
    print("  no API key or access token was read or written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
