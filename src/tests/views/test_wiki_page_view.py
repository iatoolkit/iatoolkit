from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
import yaml
from flask import Flask, url_for
from flask_injector import FlaskInjector

from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.tenant_wiki_service import TenantWikiService
from iatoolkit.views.wiki_page_view import WikiPageView

SESSION = {"company_short_name": "acme", "user_identifier": "ana@acme.com"}
WIKI = {"wiki_key": "kb", "name": "Base de conocimiento"}


@pytest.fixture
def wiki_app():
    root = Path(__file__).parents[2] / "iatoolkit"
    app = Flask(__name__, template_folder=str(root / "templates"), static_folder=str(root / "static"))
    app.secret_key = "test-secret"
    app.testing = True
    profile = MagicMock(spec=ProfileService)
    profile.get_company_by_short_name.return_value = SimpleNamespace(name="ACME")
    profile.get_current_session_info.return_value = dict(SESSION)
    branding = MagicMock(spec=BrandingService)
    branding.get_company_branding.return_value = {"name": "ACME", "css_variables": ""}
    wiki_service = MagicMock(spec=TenantWikiService)
    wiki_service.viewer_may_read_system_wiki.return_value = False
    i18n = MagicMock(spec=I18nService)
    translations = yaml.safe_load((root / "locales/es.yaml").read_text())

    def translate(key, lang=None, **kwargs):
        value = translations
        for part in key.split("."):
            value = value[part]
        return value.format(**kwargs) if kwargs else value

    i18n.t.side_effect = translate
    app.jinja_env.globals.update(t=translate)
    app.add_url_rule("/<company_short_name>/home", "home", lambda **kw: "HOME")
    app.add_url_rule("/<company_short_name>/chat", "chat", lambda **kw: "CHAT")
    view = WikiPageView.as_view("wiki_page", profile_service=profile, branding_service=branding,
                                i18n_service=i18n, tenant_wiki_service=wiki_service)
    app.add_url_rule("/<company_short_name>/wiki/<wiki_key>/", defaults={"page_path": ""}, view_func=view)
    app.add_url_rule("/<company_short_name>/wiki/<wiki_key>/<path:page_path>", view_func=view)

    @app.context_processor
    def inject_globals():
        return {"flashed_messages": [], "url_for": url_for}

    FlaskInjector(app=app)
    return app, profile, wiki_service


def served(markdown: str, *, title: str = "Notas de SG", path: str = "tech/sg/notas.md") -> dict:
    return {"status": "success", "wiki": WIKI,
            "page": {"path": path, "title": title, "markdown": markdown}}


def test_renders_the_page_as_the_signed_in_person(wiki_app):
    app, _, wiki_service = wiki_app
    wiki_service.get_page.return_value = served(
        "---\ntitle: Notas de SG\naccess: [tech]\n---\n# Notas de SG\n\nVer [alertas](../sg/alertas.md).\n"
    )

    response = app.test_client().get("/acme/wiki/kb/tech/sg/notas.md")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<h1>Notas de SG</h1>" in html
    # Relative links stay relative: the URL mirrors the page's path.
    assert 'href="../sg/alertas.md"' in html
    assert "access:" not in html
    assert "Base de conocimiento" in html
    wiki_service.get_page.assert_called_once_with(
        "acme", wiki_key="kb", path="tech/sg/notas.md", user_identifier="ana@acme.com",
    )


def test_the_wiki_folder_opens_its_root_page(wiki_app):
    app, _, wiki_service = wiki_app
    wiki_service.get_page.return_value = served("# Inicio\n\n- [Notas](tech/sg/notas.md)\n", title="Inicio", path="/")

    response = app.test_client().get("/acme/wiki/kb/")

    assert response.status_code == 200
    assert 'href="tech/sg/notas.md"' in response.get_data(as_text=True)
    assert wiki_service.get_page.call_args.kwargs["path"] == "/"


def test_a_link_from_the_wiki_root_stays_inside_the_wiki(wiki_app):
    # kb-integrated writes `/tech/x.md` for the wiki's own tech/x.md; the browser
    # would take it from the host's root and drop /acme/wiki/kb.
    app, _, wiki_service = wiki_app
    wiki_service.get_page.return_value = served(
        "# Notas\n\n"
        "[datos](/tech/sg/05-data.md) [mismo dir](alertas.md) [arriba](../INDEX.md) "
        "[fuera](https://example.com/x) [otro host](//example.com/x) [aqui](#tablas)\n"
    )

    html = app.test_client().get("/acme/wiki/kb/tech/sg/notas.md").get_data(as_text=True)

    assert 'href="/acme/wiki/kb/tech/sg/05-data.md"' in html
    assert 'href="alertas.md"' in html and 'href="../INDEX.md"' in html
    assert 'href="https://example.com/x"' in html
    assert 'href="//example.com/x"' in html
    assert 'href="#tablas"' in html


def test_the_browser_title_is_plain_text(wiki_app):
    app, _, wiki_service = wiki_app
    wiki_service.get_page.return_value = served("# x\n", title="`credits-app` — **Datos** de SYS_alertas_push")

    html = app.test_client().get("/acme/wiki/kb/tech/sg/notas.md").get_data(as_text=True)

    assert "<title>credits-app — Datos de SYS_alertas_push · Base de conocimiento</title>" in html


def test_underscores_in_names_are_not_italics(wiki_app):
    app, _, wiki_service = wiki_app
    wiki_service.get_page.return_value = served("# SYS_alertas_push\n\nLa tabla DTE_doc_noti.\n")

    html = app.test_client().get("/acme/wiki/kb/tech/sg/notas.md").get_data(as_text=True)

    assert "<h1>SYS_alertas_push</h1>" in html
    assert "DTE_doc_noti" in html


def test_page_markup_is_sanitized(wiki_app):
    app, _, wiki_service = wiki_app
    wiki_service.get_page.return_value = served("# Notas\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))\n")

    html = app.test_client().get("/acme/wiki/kb/tech/sg/notas.md").get_data(as_text=True)

    assert "alert(1)</script>" not in html
    assert "javascript:" not in html


@pytest.mark.parametrize("session_info", [{}, {"company_short_name": "other", "user_identifier": "ana@acme.com"}])
def test_without_a_session_for_the_company_it_signs_in_and_comes_back(wiki_app, session_info):
    app, profile, wiki_service = wiki_app
    profile.get_current_session_info.return_value = session_info

    response = app.test_client().get("/acme/wiki/kb/tech/sg/notas.md")

    assert response.status_code == 302
    location = urlparse(response.headers["Location"])
    assert location.path == "/acme/home"
    assert parse_qs(location.query)["next"] == ["/acme/wiki/kb/tech/sg/notas.md"]
    wiki_service.get_page.assert_not_called()


def test_a_withheld_page_names_the_labels_it_needs(wiki_app):
    app, _, wiki_service = wiki_app
    wiki_service.get_page.return_value = {
        "status": "forbidden", "wiki": WIKI, "wiki_key": "kb", "path": "board/comp.md",
        "required_labels": ["board", "finance"], "held_labels": ["tech"],
    }

    response = app.test_client().get("/acme/wiki/kb/board/comp.md")

    assert response.status_code == 403
    assert "board, finance" in response.get_data(as_text=True)


def test_unverifiable_access_is_not_a_denial(wiki_app):
    app, _, wiki_service = wiki_app
    wiki_service.get_page.return_value = {"status": "unavailable", "wiki": WIKI, "required_labels": []}

    response = app.test_client().get("/acme/wiki/kb/board/comp.md")

    assert response.status_code == 503
    assert "No pudimos verificar tu acceso" in response.get_data(as_text=True)


def test_a_missing_page_is_a_404(wiki_app):
    app, _, wiki_service = wiki_app
    wiki_service.get_page.return_value = {"status": "error", "error_message": "page not found"}

    response = app.test_client().get("/acme/wiki/kb/tech/nada.md")

    assert response.status_code == 404
    assert "no existe en la wiki" in response.get_data(as_text=True)


def test_an_unknown_company_is_a_404(wiki_app):
    app, profile, wiki_service = wiki_app
    profile.get_company_by_short_name.return_value = None

    response = app.test_client().get("/nadie/wiki/kb/tech/sg/notas.md")

    assert response.status_code == 404
    wiki_service.get_page.assert_not_called()


def test_memorias_wiki_opens_for_who_the_service_lets_in(wiki_app):
    app, profile, wiki_service = wiki_app
    wiki_service.viewer_may_read_system_wiki.return_value = True
    # The person is asked about, never the role in the session profile an SSO hook
    # writes (BL-010, Fases 0 y 1).
    profile.get_current_session_info.return_value = {**SESSION, "profile": {"user_role": "admin"}}
    wiki_service.get_page.return_value = served("# Créditos\n\nPlazo 30. (Política de crédito v3, 2026-10-16)\n",
                                                title="Créditos", path="creditos.md")

    response = app.test_client().get("/acme/wiki/iatoolkit-memory/creditos.md")

    assert response.status_code == 200
    wiki_service.viewer_may_read_system_wiki.assert_called_once_with(
        "acme", "iatoolkit-memory", SESSION["user_identifier"])
    assert wiki_service.get_page.call_args.kwargs["include_system"] is True


def test_system_wiki_readers_are_registered_per_feature(monkeypatch):
    from iatoolkit.common import access
    from iatoolkit.services.memory_wiki_service import MemoryWikiService

    service = TenantWikiService.__new__(TenantWikiService)
    company = SimpleNamespace(id=1)
    service._get_company = lambda short_name: company
    wikis = {"iatoolkit-memory": SimpleNamespace(settings={TenantWikiService.SYSTEM_OWNER_SETTING: MemoryWikiService.SYSTEM_OWNER}),
             "kb": SimpleNamespace(settings={})}
    service.knowledge_wiki_repo = SimpleNamespace(get_wiki_by_key=lambda company_id, key: wikis.get(key))
    roles = {"duena@acme.cl": "owner", "admin@acme.cl": "admin", "editor@acme.cl": "editor"}
    monkeypatch.setattr(access.Access, "_decider", access.RoleAccessDecider(lambda c, u: roles.get(u)))

    # Memoria's wiki: for those who administer the company.
    assert service.viewer_may_read_system_wiki("acme", "iatoolkit-memory", "duena@acme.cl") is True
    assert service.viewer_may_read_system_wiki("acme", "iatoolkit-memory", "admin@acme.cl") is True
    assert service.viewer_may_read_system_wiki("acme", "iatoolkit-memory", "editor@acme.cl") is False
    assert service.viewer_may_read_system_wiki("acme", "iatoolkit-memory", None) is False
    # Not a system wiki: the normal rules apply, nothing to open.
    assert service.viewer_may_read_system_wiki("acme", "kb", "admin@acme.cl") is False
