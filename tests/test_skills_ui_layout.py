from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def test_skills_grid_spans_exist():
    assert ".span-7{grid-column:span 7}" in CSS
    assert ".span-5{grid-column:span 5}" in CSS
    assert 'class="card card-pad span-7"' in HTML
    assert 'class="card card-pad span-5"' in HTML


def test_skills_responsive_stack_and_min_width():
    assert ".skills-layout>.card{min-width:0}" in CSS
    assert "@media(max-width:1280px){#skills .span-7,#skills .span-5{grid-column:span 12}" in CSS
    assert ".skills-scroll{width:100%;" in CSS


def test_skills_assets_cache_busted():
    assert '/static/app.css?v=1.4.0' in HTML
    assert '/static/app.js?v=1.4.0' in HTML
