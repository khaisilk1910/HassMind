import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")


def _example_names():
    block = JS.split("const SKILL_PROMPT_EXAMPLES=[", 1)[1].split("];", 1)[0]
    return re.findall(r"\{skill:'([^']+)'", block)


def test_chat_has_collapsible_21_skill_prompt_library():
    names = _example_names()
    builtins = sorted(path.stem for path in (ROOT / "config" / "skills").glob("*.md"))
    assert len(names) == 21
    assert len(set(names)) == 21
    assert sorted(names) == builtins
    assert 'id="skillPromptExamples"' in HTML
    assert 'id="skillPromptList"' in HTML
    assert '21 mẫu' in HTML
    assert ".skill-prompt-list{" in CSS


def test_skills_page_has_scenario_dry_run_controls():
    for control in ("skillDryRunSelect", "skillDryRunPrompt", "skillDryRunBtn", "skillDryRunResult"):
        assert f'id="{control}"' in HTML
    assert "/api/skills/" in JS and "/dry-run" in JS
    assert "NO — Dry Run" in JS
    assert "actions_executed" in JS
