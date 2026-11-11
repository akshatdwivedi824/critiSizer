from pathlib import Path

import pytest

import critisizer.scoring.prompt as prompt_module

PROMPTS = Path(prompt_module.__file__).parent / "prompts"


@pytest.mark.parametrize(
    "name", ["score_v1.txt", "score_v2.txt", "score_v3.txt", "score_v4.txt"]
)
def test_every_prompt_version_file_exists(name):
    path = PROMPTS / name
    assert path.is_file(), f"missing prompt file: {path}"
    assert path.read_text(encoding="utf-8").strip(), f"empty prompt file: {path}"