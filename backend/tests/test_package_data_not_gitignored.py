"""Package data under backend/packages must not be hidden by .gitignore.

CI builds images from the git checkout, so an ignored data file exists on a
developer machine but is missing in the image. A broad ``prompts/`` rule once
hid DeerMem's prompt yaml files and the backend was skipped at startup.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES = REPO_ROOT / "backend" / "packages"
DATA_SUFFIXES = {".yaml", ".yml", ".json", ".txt", ".md", ".jinja", ".j2", ".toml"}
DEERMEM_PROMPTS = PACKAGES / "harness/deerflow/agents/memory/backends/deermem/deermem/core/prompts"


def _package_data_files() -> list[str]:
    return sorted(str(path.relative_to(REPO_ROOT)) for path in PACKAGES.rglob("*") if path.is_file() and path.suffix in DATA_SUFFIXES and not {"__pycache__", ".venv", "node_modules"} & set(path.parts))


@pytest.mark.skipif(shutil.which("git") is None or not (REPO_ROOT / ".git").exists(), reason="needs a git checkout")
def test_no_package_data_file_is_gitignored():
    files = _package_data_files()
    assert any(name.startswith(str(DEERMEM_PROMPTS.relative_to(REPO_ROOT))) for name in files)
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=REPO_ROOT,
        input="\n".join(files),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout.split() == []


def test_deermem_prompt_templates_are_present():
    names = {path.name for path in DEERMEM_PROMPTS.glob("*.yaml")}
    assert {"consolidation.yaml", "fact_extraction.yaml", "memory_update.chat.yaml", "staleness_review.yaml"} <= names
