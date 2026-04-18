"""Tests for the discover results page and refine functionality."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from app.main import app
from app.services.discovery_cache import update_discovery


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_discovery_data():
    """Sample discovery data for testing."""
    return {
        "url": "https://example.com",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": {
            "page_meta": {
                "title": "Example Site",
                "description": "An example website",
            },
            "rss_feeds": [
                {
                    "url": "https://example.com/feed.xml",
                    "feed_type": "rss",
                    "is_alive": True,
                    "http_status": 200,
                }
            ],
            "api_endpoints": [],
            "embedded_json": [],
            "xpath_candidates": [
                {
                    "item_selector": "//article",
                    "title_selector": ".//h2/text()",
                    "link_selector": ".//a/@href",
                    "content_selector": ".//div[@class='content']",
                    "timestamp_selector": ".//time/@datetime",
                    "thumbnail_selector": ".//img/@src",
                    "confidence": 0.85,
                    "item_count": 10,
                }
            ],
            "graphql_operations": [],
        },
        "errors": [],
    }


class TestDiscoverResultsPage:
    """Test cases for the discover results page."""

    def test_discover_results_renders_with_xpath_candidates(self, client, mock_discovery_data):
        """Discover results page should render with XPath candidates."""
        discover_id = "test-123"
        
        with patch("app.services.discovery_cache.load_discovery", return_value=mock_discovery_data):
            response = client.get(f"/d/{discover_id}")
            
        assert response.status_code == 200
        html = response.text
        
        # Should contain the candidate card
        assert "card-xpath-0" in html
        assert "XPath" in html
        # Should show confidence
        assert "85% match" in html

    def test_discover_results_includes_initCandidateRefine(self, client, mock_discovery_data):
        """Page should load app.js which contains initCandidateRefine."""
        discover_id = "test-123"
        
        with patch("app.services.discovery_cache.load_discovery", return_value=mock_discovery_data):
            response = client.get(f"/d/{discover_id}")
            
        assert response.status_code == 200
        html = response.text
        
        # The app.js should be loaded (contains initCandidateRefine)
        assert "/static/app.js" in html
        # The function should be defined in app.js (checked separately)
        # We verify the function exists by reading the JS file
        import os
        app_js_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "app.js")
        with open(app_js_path) as f:
            app_js = f.read()
        assert "function initCandidateRefine()" in app_js
        assert "initCandidateRefine();" in app_js

    def test_discover_results_includes_global_refine_form(self, client, mock_discovery_data):
        """Page should include the global refine form."""
        discover_id = "test-123"
        
        with patch("app.services.discovery_cache.load_discovery", return_value=mock_discovery_data):
            response = client.get(f"/d/{discover_id}")
            
        assert response.status_code == 200
        html = response.text
        
        # Should have the global refine form
        assert "global-refine-form" in html
        # Should have refine input fields
        assert "title_examples" in html

    def test_discover_results_includes_per_candidate_refine_panel(self, client, mock_discovery_data):
        """Each candidate should have a refine panel."""
        discover_id = "test-123"
        
        with patch("app.services.discovery_cache.load_discovery", return_value=mock_discovery_data):
            response = client.get(f"/d/{discover_id}")
            
        assert response.status_code == 200
        html = response.text
        
        # Should have refine panel for the candidate
        assert "refine-panel-xpath-0" in html
        # Should have refine button
        assert "card-refine-btn" in html

    def test_discover_results_filters_dead_rss_feeds(self, client):
        """Dead RSS feeds should be filtered out."""
        # Discovery data with dead RSS feed
        data_with_dead_rss = {
            "url": "https://example.com",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": {
                "page_meta": {"title": "Example"},
                "rss_feeds": [
                    {"url": "https://example.com/dead.xml", "feed_type": "rss", "is_alive": False, "http_status": 404},
                    {"url": "https://example.com/alive.xml", "feed_type": "rss", "is_alive": True, "http_status": 200},
                ],
                "api_endpoints": [],
                "embedded_json": [],
                "xpath_candidates": [],
                "graphql_operations": [],
            },
            "errors": [],
        }
        
        discover_id = "test-dead-rss"
        
        with patch("app.services.discovery_cache.load_discovery", return_value=data_with_dead_rss):
            response = client.get(f"/d/{discover_id}")
            
        assert response.status_code == 200
        html = response.text
        
        # Dead RSS should not appear
        assert "dead.xml" not in html
        # Live RSS should appear
        assert "alive.xml" in html

    def test_discover_results_filters_empty_api_endpoints(self, client):
        """API endpoints with < 3 items and low score should be filtered."""
        data_with_empty_api = {
            "url": "https://example.com",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": {
                "page_meta": {"title": "Example"},
                "rss_feeds": [],
                "api_endpoints": [
                    {"url": "https://api.example.com/endpoint-empty", "item_count": 0, "feed_score": 0.1},
                    {"url": "https://api.example.com/endpoint-good", "item_count": 5, "feed_score": 0.5},
                    {"url": "https://api.example.com/endpoint-highscore", "item_count": 1, "feed_score": 0.4},
                ],
                "embedded_json": [],
                "xpath_candidates": [],
                "graphql_operations": [],
            },
            "errors": [],
        }
        
        discover_id = "test-empty-api"
        
        with patch("app.services.discovery_cache.load_discovery", return_value=data_with_empty_api):
            response = client.get(f"/d/{discover_id}")
            
        assert response.status_code == 200
        html = response.text
        
        # Empty API (0 items, low score) should not appear
        assert "endpoint-empty" not in html
        # Good API (5 items) should appear
        assert "endpoint-good" in html
        # High score API should appear (score >= 0.3)
        assert "endpoint-highscore" in html

    def test_discover_results_shows_empty_note_for_rss(self, client):
        """When all RSS feeds are dead, show empty note."""
        data_all_dead = {
            "url": "https://example.com",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": {
                "page_meta": {"title": "Example"},
                "rss_feeds": [
                    {"url": "https://example.com/dead.xml", "feed_type": "rss", "is_alive": False, "http_status": 404},
                ],
                "api_endpoints": [],
                "embedded_json": [],
                "xpath_candidates": [],
                "graphql_operations": [],
            },
            "errors": [],
        }
        
        discover_id = "test-all-dead"
        
        with patch("app.services.discovery_cache.load_discovery", return_value=data_all_dead):
            response = client.get(f"/d/{discover_id}")
            
        assert response.status_code == 200
        html = response.text
        
        # Should show the empty note
        assert "No viable RSS or Atom feed found" in html

    def test_preview_table_shows_link_text(self, client, mock_discovery_data):
        """Preview table template should show actual URL text, not 'open ↗'."""
        # The preview table is loaded via AJAX, so we check the template directly
        import os
        template_path = os.path.join(os.path.dirname(__file__), "..", "app", "ui", "templates", "partials", "preview_table.html")
        with open(template_path) as f:
            template_content = f.read()
        
        # Should NOT have the old "open ↗" link
        assert "open ↗" not in template_content
        # Should have preview-link class for styling
        assert "preview-link" in template_content
        # Should have logic to show URL text
        assert "preview-link text-mono" in template_content


class TestPreviewFragmentRefined:
    """Test cases for the /preview-fragment-refined endpoint."""

    def test_preview_refined_with_examples_only_runs_xpath(self, client, mock_discovery_data):
        """When refine_examples are provided, only XPath candidates are re-run;
        non-XPath types are skipped (they don't benefit from text examples)."""
        from app.models.schemas import ScrapeItem
        from scrapling import Selector

        mock_items = [
            ScrapeItem(
                title="Test Item",
                link="https://example.com/item1",
                timestamp="2024-01-01T00:00:00Z",
            )
        ]

        discover_id = "test-refine-examples"

        html_stub = "<html><body></body></html>"
        sel_stub = Selector(html_stub)

        with patch("app.services.discovery_cache.load_discovery", return_value=mock_discovery_data):
            with patch("app.services.discovery_cache.update_discovery"):
                with patch(
                    "app.scraping.scrape.fetch_and_parse",
                    new_callable=AsyncMock,
                    return_value=(html_stub, sel_stub, "httpx"),
                ):
                    with patch(
                        "app.scraping.scrape._scrape_xpath_from_selector",
                        new_callable=AsyncMock,
                        return_value=(mock_items, [], None),
                    ):
                        response = client.post(
                            "/preview-fragment-refined",
                            data={
                                "discover_id": discover_id,
                                "title_examples": "Example Title",
                            },
                        )

        assert response.status_code == 200
        data = response.json()

        # XPath candidates should be present (processed via shared fetch)
        assert "xpath" in data
        # Non-XPath types are skipped when examples are provided
        assert "rss" not in data

    @patch("app.scraping.scrape.run_scrape")
    def test_preview_refined_without_examples_runs_all_types(self, mock_scrape, client, mock_discovery_data):
        """Without refine_examples, all candidate types are refreshed."""
        from app.models.schemas import ScrapeResponse, ScrapeItem, FeedStrategy

        mock_items = [
            ScrapeItem(
                title="Test Item",
                link="https://example.com/item1",
                timestamp="2024-01-01T00:00:00Z",
            )
        ]
        mock_scrape.return_value = ScrapeResponse(
            url="https://example.com",
            timestamp=datetime.now(timezone.utc),
            strategy=FeedStrategy.XPATH,
            items=mock_items,
            item_count=1,
            fetch_backend_used="bundled",
        )

        discover_id = "test-refine-no-examples"

        with patch("app.services.discovery_cache.load_discovery", return_value=mock_discovery_data):
            with patch("app.services.discovery_cache.update_discovery"):
                response = client.post(
                    "/preview-fragment-refined",
                    data={"discover_id": discover_id},
                )

        assert response.status_code == 200
        data = response.json()

        # Both XPath and RSS should be present when no examples given
        assert "xpath" in data
        assert "rss" in data

    def test_preview_refined_requires_valid_discover_id(self, client):
        """Preview refined should return error for invalid discover_id."""
        response = client.post(
            "/preview-fragment-refined",
            data={
                "discover_id": "nonexistent-id",
                "title_examples": "test",
            },
        )
        
        assert response.status_code == 400
        assert "error" in response.json()