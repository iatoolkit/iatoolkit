import pytest
from unittest.mock import MagicMock
from flask import Flask

from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.memory_service import MemoryService
from iatoolkit.views.memory_api_view import MemoryApiView


class TestMemoryApiView:
    @staticmethod
    def create_app():
        app = Flask(__name__)
        app.testing = True
        return app

    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = self.create_app()
        self.client = self.app.test_client()
        self.auth_service = MagicMock(spec=AuthService)
        self.memory_service = MagicMock(spec=MemoryService)
        self.auth_service.verify_for_company.return_value = {
            "success": True,
            "user_identifier": "user@example.com",
        }

        view = MemoryApiView.as_view(
            "memory_api_test",
            auth_service=self.auth_service,
            memory_service=self.memory_service,
        )
        self.app.add_url_rule("/<company_short_name>/api/memory", view_func=view, methods=["GET", "POST"])
        self.app.add_url_rule("/<company_short_name>/api/memory/pages/<int:page_id>", view_func=view, methods=["GET"])

    def test_get_dashboard(self):
        self.memory_service.get_memory_dashboard.return_value = {
            "status": "success",
            "recent_items": [],
            "pages": [],
        }

        response = self.client.get("/acme/api/memory")

        assert response.status_code == 200
        self.memory_service.get_memory_dashboard.assert_called_once_with("acme", "user@example.com")

    def test_post_save_item(self):
        self.memory_service.save_item.return_value = {"status": "success", "item": {"id": 1}}

        response = self.client.post("/acme/api/memory", json={
            "item_type": "note",
            "content_text": "hola",
            "title": "hola",
        })

        assert response.status_code == 200
        self.memory_service.save_item.assert_called_once()

    def test_post_search(self):
        self.memory_service.search_pages.return_value = {"status": "success", "results": []}

        response = self.client.post("/acme/api/memory", json={
            "action": "search",
            "query": "onboarding",
            "limit": 3,
        })

        assert response.status_code == 200
        self.memory_service.search_pages.assert_called_once_with("acme", "user@example.com", query="onboarding", limit=3)

    def test_post_lint(self):
        self.memory_service.lint_memory_wiki.return_value = {
            "status": "success",
            "mode": "inline",
            "lint": {"checked_pages": 2},
        }

        response = self.client.post("/acme/api/memory", json={
            "action": "lint",
        })

        assert response.status_code == 200
        self.memory_service.lint_memory_wiki.assert_called_once_with("acme", "user@example.com")

    def test_post_lint_async(self):
        self.memory_service.lint_memory_wiki.return_value = {
            "status": "success",
            "mode": "async_task",
            "lint": None,
            "task": {"task_id": 19, "task_status": "pending"},
        }

        response = self.client.post("/acme/api/memory", json={"action": "lint"})

        assert response.status_code == 200
        assert response.get_json()["mode"] == "async_task"

    def test_post_delete_item(self):
        self.memory_service.delete_item.return_value = {"status": "success", "deleted_item_id": 9}

        response = self.client.post("/acme/api/memory", json={
            "action": "delete_item",
            "item_id": 9,
        })

        assert response.status_code == 200
        self.memory_service.delete_item.assert_called_once_with("acme", "user@example.com", item_id=9)

    def test_post_save_capture(self):
        self.memory_service.save_capture.return_value = {"status": "success", "capture": {"capture_id": 5}}

        response = self.client.post("/acme/api/memory", json={
            "action": "save_capture",
            "capture_text": "hola",
            "items": [{"item_type": "note", "content_text": "hola", "title": "hola"}],
        })

        assert response.status_code == 200
        self.memory_service.save_capture.assert_called_once_with(
            company_short_name="acme",
            user_identifier="user@example.com",
            capture_text="hola",
            title=None,
            new_items=[{"item_type": "note", "content_text": "hola", "title": "hola"}],
        )

    def test_post_update_capture(self):
        self.memory_service.update_capture.return_value = {"status": "success", "capture": {"capture_id": 5}}

        response = self.client.post("/acme/api/memory", json={
            "action": "update_capture",
            "capture_id": 5,
            "capture_text": "hola 2",
            "keep_item_ids": [11],
            "items": [{"item_type": "note", "content_text": "hola 2", "title": "hola 2"}],
        })

        assert response.status_code == 200
        self.memory_service.update_capture.assert_called_once_with(
            company_short_name="acme",
            user_identifier="user@example.com",
            capture_id=5,
            capture_text="hola 2",
            title=None,
            keep_item_ids=[11],
            new_items=[{"item_type": "note", "content_text": "hola 2", "title": "hola 2"}],
        )

    def test_post_delete_capture(self):
        self.memory_service.delete_capture.return_value = {"status": "success", "deleted_capture_id": 5}

        response = self.client.post("/acme/api/memory", json={
            "action": "delete_capture",
            "capture_id": 5,
        })

        assert response.status_code == 200
        self.memory_service.delete_capture.assert_called_once_with("acme", "user@example.com", capture_id=5)
