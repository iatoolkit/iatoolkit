# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import markdown2
import nh3
from flask import redirect, render_template, request, url_for
from flask.views import MethodView
from injector import inject

from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.markdown_wiki_service import MarkdownWikiService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.tenant_wiki_service import TenantWikiService


class WikiPageView(MethodView):
    """
    A knowledge wiki page, read in the browser.

    The link the wiki tools hand out (`TenantWikiService.page_url`) lands here.
    The page is read as the signed-in person, so its visibility labels apply
    exactly as they do in chat; without a session the person signs in and comes
    back. The URL mirrors the page's path in the wiki, so a relative link between
    pages resolves by itself; one that starts with "/" means the wiki's root, as
    the wiki's lint reads it, and is rewritten under this viewer.
    """

    # `code-friendly`: in a technical wiki an underscore joins a name
    # (SYS_alertas_push), it does not start italics.
    MARKDOWN_EXTRAS = ["tables", "fenced-code-blocks", "strike", "task_list", "code-friendly"]

    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService,
                 i18n_service: I18nService,
                 tenant_wiki_service: TenantWikiService):
        self.profile_service = profile_service
        self.branding_service = branding_service
        self.i18n_service = i18n_service
        self.tenant_wiki_service = tenant_wiki_service

    def get(self, company_short_name: str, wiki_key: str, page_path: str = ""):
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html',
                                   message=self.i18n_service.t('errors.templates.company_not_found')), 404

        session_info = self.profile_service.get_current_session_info(company_short_name=company_short_name) or {}
        user_identifier = session_info.get('user_identifier')
        if not user_identifier or session_info.get('company_short_name') != company_short_name:
            # The home page carries `next` into its login widget.
            return redirect(url_for('home', company_short_name=company_short_name,
                                    next=request.full_path.rstrip('?')))

        result = self.tenant_wiki_service.get_page(
            company_short_name,
            wiki_key=wiki_key,
            path=page_path or "/",
            user_identifier=user_identifier,
        )
        wiki = result.get("wiki") or {}
        context = {
            "company_short_name": company_short_name,
            "branding": self.branding_service.get_company_branding(company_short_name),
            "wiki_name": wiki.get("name") or wiki_key,
            "root_url": url_for('wiki_page', company_short_name=company_short_name,
                                wiki_key=wiki_key, page_path=''),
            "page_path": page_path,
        }

        if result.get("status") == "success":
            page = result.get("page") or {}
            body = MarkdownWikiService.parse_frontmatter_document(page.get("markdown") or "").get("body")
            return render_template(
                "wiki_page.html",
                **context,
                page_title=page.get("title") or page_path or context["wiki_name"],
                body_html=self.render_markdown(body, wiki_root=context["root_url"]),
                message=None if body else self.i18n_service.t('ui.wiki_page.empty'),
            )

        status_code, message = self._denial(result)
        return render_template(
            "wiki_page.html",
            **context,
            page_title=page_path or context["wiki_name"],
            body_html="",
            message=message,
        ), status_code

    @classmethod
    def render_markdown(cls, markdown: str | None, wiki_root: str | None = None) -> str:
        """
        Sanitized HTML for a page body. With `wiki_root` (the viewer URL of the
        wiki's root page), a link that starts with "/" is taken as a path in the
        wiki and moved under it: written by hand or by a generator,
        `/tech/x.md` means the wiki's `tech/x.md`, never the host's.
        """
        if not str(markdown or "").strip():
            return ""
        prefix = str(wiki_root or "").rstrip("/")

        def under_wiki_root(tag: str, attribute: str, value: str) -> str:
            if prefix and tag == "a" and attribute == "href" and value.startswith("/") \
                    and not value.startswith("//"):
                return prefix + value
            return value

        return nh3.clean(markdown2.markdown(markdown, extras=cls.MARKDOWN_EXTRAS),
                         attribute_filter=under_wiki_root)

    def _denial(self, result: dict) -> tuple[int, str]:
        """A withheld page says why, as the wiki tools do; anything else is a 404."""
        status = result.get("status")
        if status == TenantWikiService.ACCESS_STATUS_UNAVAILABLE:
            return 503, self.i18n_service.t('ui.wiki_page.unavailable')
        if status == TenantWikiService.ACCESS_STATUS_FORBIDDEN:
            labels = ", ".join(result.get("required_labels") or [])
            if labels:
                return 403, self.i18n_service.t('ui.wiki_page.forbidden_labels', labels=labels)
            return 403, self.i18n_service.t('ui.wiki_page.forbidden')
        return 404, self.i18n_service.t('ui.wiki_page.not_found')
