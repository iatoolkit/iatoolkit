from unittest.mock import MagicMock

from iatoolkit.services.markdown_wiki_service import MarkdownWikiService
from iatoolkit.services.storage_service import StorageService


class TestMarkdownWikiService:
    def setup_method(self):
        self.storage_service = MagicMock(spec=StorageService)
        self.service = MarkdownWikiService(storage_service=self.storage_service)

    def test_frontmatter_document_roundtrip(self):
        markdown = self.service.render_frontmatter_document(
            {
                "title": "Pricing Playbook",
                "tags": ["sales", "pricing"],
            },
            "# Pricing\n\nUse approved ranges.",
        )

        parsed = self.service.parse_frontmatter_document(markdown)

        assert parsed["frontmatter"]["title"] == "Pricing Playbook"
        assert parsed["frontmatter"]["tags"] == ["sales", "pricing"]
        assert parsed["body"] == "# Pricing\n\nUse approved ranges."

    def test_generic_index_roundtrip(self):
        markdown = self.service.render_generic_index(
            [
                {
                    "path": "pages/pricing.md",
                    "title": "Pricing",
                    "summary": "Commercial pricing rules.",
                    "tags": ["sales"],
                }
            ],
            title="Sales Wiki",
        )

        parsed = self.service.parse_generic_index(markdown)

        assert len(parsed["entries"]) == 1
        assert parsed["entries"][0]["path"] == "pages/pricing.md"
        assert parsed["entries"][0]["title"] == "Pricing"
        assert parsed["entries"][0]["tags"] == ["sales"]

    def test_read_and_write_markdown_use_storage(self):
        self.storage_service.get_document_content.return_value = b"# Page"

        storage_key = self.service.write_markdown("acme", "knowledge/wiki.md", "# Page")
        markdown = self.service.read_markdown("acme", "knowledge/wiki.md")

        assert storage_key == "knowledge/wiki.md"
        assert markdown == "# Page"
        self.storage_service.upload_bytes.assert_called_once_with(
            company_short_name="acme",
            storage_key="knowledge/wiki.md",
            file_content=b"# Page",
            mime_type="text/markdown",
        )

    def test_log_roundtrip(self):
        markdown = self.service.render_log(
            [
                {
                    "timestamp": "2026-06-15T12:00:00+00:00",
                    "entry_type": "sync",
                    "title": "Published sales wiki",
                    "details": ["Indexed 12 pages."],
                    "metadata": {"wiki_key": "sales"},
                }
            ]
        )

        parsed = self.service.parse_log(markdown)

        assert len(parsed) == 1
        assert parsed[0]["entry_type"] == "sync"
        assert parsed[0]["title"] == "Published sales wiki"
        assert parsed[0]["metadata"]["wiki_key"] == "sales"
