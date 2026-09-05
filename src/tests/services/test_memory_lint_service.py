from types import SimpleNamespace
from unittest.mock import MagicMock

from iatoolkit.services.memory_lint_service import MemoryLintService


def _service():
    return MemoryLintService(
        profile_repo=MagicMock(),
        memory_repo=MagicMock(),
        memory_wiki_service=MagicMock(),
        memory_compiler_service=MagicMock(),
    )


def test_lint_page_payload_dedupes_lists_and_source_item_ids():
    service = _service()

    linted, changed = service._lint_page_payload({
        "title": "Project",
        "summary": "Project",
        "key_points": [" Keep ", "keep", "", None, "Another"],
        "decisions": ["Ship", " ship "],
        "open_questions": [],
        "next_steps": [None, "Call"],
        "related_pages": ["Árbol", "arbol"],
        "sources": [" email ", "email"],
        "source_item_ids": [7, "7", 7, 9, None],
    })

    assert changed is True
    assert linted["key_points"] == ["Keep", "Another"]
    assert linted["decisions"] == ["Ship"]
    assert linted["next_steps"] == ["Call"]
    assert linted["related_pages"] == ["Árbol"]
    assert linted["sources"] == ["email"]
    assert linted["source_item_ids"] == [7, 9]


def test_get_last_lint_result_returns_latest_lint_entry():
    service = _service()
    service.memory_wiki_service.read_log.return_value = [
        {"entry_type": "compile", "title": "Ignored"},
        {
            "entry_type": "lint",
            "title": "Old lint",
            "timestamp": "2026-01-01T00:00:00Z",
            "metadata": {"checked_pages": 1, "actions_applied": 1},
            "details": ["old"],
        },
        {
            "entry_type": "lint",
            "timestamp": "2026-01-02T00:00:00Z",
            "metadata": {
                "checked_pages": "3",
                "actions_applied": "2",
                "duplicate_candidates": "1",
                "orphan_pages": "4",
            },
            "details": ["new"],
        },
    ]

    result = service.get_last_lint_result("acme", "user-1")

    assert result == {
        "title": "Memory wiki health check",
        "timestamp": "2026-01-02T00:00:00Z",
        "checked_pages": 3,
        "actions_applied": 2,
        "duplicate_candidates": 1,
        "orphan_pages": 4,
        "details": ["new"],
    }


def test_safe_read_page_returns_empty_dict_for_missing_path_or_read_error():
    service = _service()
    service.memory_wiki_service.read_page.side_effect = RuntimeError("missing")

    assert service._safe_read_page("acme", None) == {}
    assert service._safe_read_page("acme", "page.md") == {}


def test_run_memory_lint_cleans_pages_detects_duplicates_and_orphans():
    service = _service()
    company = SimpleNamespace(id=42, short_name="acme")
    pages = [
        SimpleNamespace(id=1, title="Plan", slug="plan", summary="old summary", wiki_path="plan.md"),
        SimpleNamespace(id=2, title="plan", slug="plan-copy", summary="", wiki_path="plan-copy.md"),
        SimpleNamespace(id=3, title="Loose", slug="loose", summary="", wiki_path="loose.md"),
    ]
    page_payloads = {
        "plan.md": {
            "title": "Plan",
            "slug": "plan",
            "summary": "new summary",
            "key_points": ["A", "a"],
            "related_pages": [],
            "source_item_ids": [1, 1, "1"],
        },
        "plan-copy.md": {
            "title": "plan",
            "slug": "plan-copy",
            "summary": "copy",
            "related_pages": ["Plan"],
            "source_item_ids": [],
        },
        "loose.md": {
            "title": "Loose",
            "slug": "loose",
            "summary": "Loose",
            "related_pages": [],
            "source_item_ids": [3],
        },
    }

    service.profile_repo.get_company_by_short_name.return_value = company
    service.memory_repo.list_pages.side_effect = [pages, pages]
    service.memory_wiki_service.read_page.side_effect = lambda _company, path: dict(page_payloads[path])
    service.memory_wiki_service.slugify.side_effect = lambda value: str(value).strip().lower().replace(" ", "-")
    service.memory_wiki_service.read_log.return_value = [
        {"entry_type": "lint", "timestamp": "2026-09-05T12:00:00Z", "metadata": {}}
    ]

    result = service.run_memory_lint("acme", "user-1")

    assert result["status"] == "success"
    assert result["lint"]["checked_pages"] == 3
    assert result["lint"]["actions_applied"] == 1
    assert result["lint"]["cleaned_pages"] == [{"page_id": 1, "title": "Plan"}]
    assert result["lint"]["duplicate_candidates"] == [{"title": "Plan", "page_ids": [1, 2]}]
    assert result["lint"]["orphan_pages"] == [{"page_id": 3, "title": "Loose"}]
    assert result["lint"]["ran_at"] == "2026-09-05T12:00:00Z"
    service.memory_compiler_service.compile_pending_for_user.assert_called_once_with("acme", "user-1")
    service.memory_wiki_service.ensure_wiki_bootstrap.assert_called_once_with("acme", "user-1")
    service.memory_wiki_service.write_page.assert_called_once()
    service.memory_repo.commit.assert_called_once()
    service.memory_wiki_service.rebuild_index.assert_called_once()
    service.memory_wiki_service.append_log_entry.assert_called_once()


def test_run_memory_lint_returns_error_when_company_is_missing():
    service = _service()
    service.profile_repo.get_company_by_short_name.return_value = None

    result = service.run_memory_lint("missing", "user-1")

    assert result == {"status": "error", "error_message": "company not found"}
    service.memory_compiler_service.compile_pending_for_user.assert_called_once_with("missing", "user-1")
    service.memory_wiki_service.ensure_wiki_bootstrap.assert_not_called()
