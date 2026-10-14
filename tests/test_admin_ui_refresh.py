"""Static regressions for the no-dependency admin UI redesign."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'static/index.html').read_text(encoding='utf-8')
JS = (ROOT / 'static/app.js').read_text(encoding='utf-8')
CSS = (ROOT / 'static/ui-refresh.css').read_text(encoding='utf-8')
LOGIN = (ROOT / 'static/login.html').read_text(encoding='utf-8')


def test_admin_navigation_and_content_remain_intact():
    assert HTML.count('class="nav-btn') == 13
    assert HTML.count('class="panel') == 13
    assert HTML.count('class="nav-icon" aria-hidden="true"') == 13
    assert 'id="chatbox"' in HTML
    assert 'id="authAuditPageSize"' in HTML
    assert 'id="authAuditPagination"' in HTML
    assert 'function initAdminPresentation()' in JS
    assert 'function setTab(id)' in JS


def test_settings_groups_keep_security_forms_and_audit_controls():
    for label in ('access', 'security', 'audit'):
        assert f'data-settings-view="{label}"' in HTML
        assert f'data-settings-panel="{label}"' in HTML
    for identifier in ('tokenForm', 'usernameForm', 'passwordForm', 'recoveryForm', 'sessionsBox', 'securityInfo', 'authAuditBox'):
        assert f'id="{identifier}"' in HTML
    assert 'function setSettingsView(view)' in JS
    assert "panel.hidden=panel.dataset.settingsPanel!==selected" in JS
    assert "button.setAttribute('aria-pressed',String(active))" in JS


def test_visual_assets_and_reduced_motion_are_versioned():
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    assert f'/static/ui-refresh.css?v={version}' in HTML
    assert f'/static/app.css?v={version}' in HTML
    assert f'/static/app.js?v={version}' in HTML
    assert f'/static/login.css?v={version}' in LOGIN
    assert 'prefers-reduced-motion:reduce' in CSS
    assert '.guide-accordion' in CSS
    assert '.settings-switcher' in CSS
    assert '.auth-audit-scroll' in CSS
