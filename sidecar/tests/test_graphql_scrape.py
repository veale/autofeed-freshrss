"""D.4 — Tests for GraphQL strategy scraping."""
from __future__ import annotations

import pytest
import respx
from httpx import Response

pytestmark = pytest.mark.asyncio


@respx.mock
async def test_graphql_replay_and_map():
    respx.post("https://api.example.com/graphql").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "posts": [
                        {"title": "A", "url": "/a", "published_at": "2024-01-01"},
                        {"title": "B", "url": "/b", "published_at": "2024-01-02"},
                    ]
                }
            },
        )
    )
    from app.scraping.scrape import run_scrape
    from app.models.schemas import (
        ScrapeRequest,
        FeedStrategy,
        GraphQLOperation,
        ScrapeSelectors,
    )

    op = GraphQLOperation(
        endpoint="https://api.example.com/graphql",
        operation_name="Posts",
        query="{ posts { title url published_at } }",
        response_path="data.posts",
    )
    req = ScrapeRequest(
        url="https://api.example.com/graphql",
        strategy=FeedStrategy.GRAPHQL,
        graphql=op,
        selectors=ScrapeSelectors(
            item_title="title",
            item_link="url",
            item_timestamp="published_at",
        ),
    )
    resp = await run_scrape(req)
    assert resp.item_count == 2
    assert resp.items[0].title == "A"
    assert resp.items[0].link == "/a"
    assert resp.items[1].title == "B"
    assert resp.errors == []


@respx.mock
async def test_graphql_with_variables():
    respx.post("https://api.example.com/graphql").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "feed": [
                        {"headline": "First", "permalink": "https://x.com/1"},
                    ]
                }
            },
        )
    )
    from app.scraping.scrape import run_scrape
    from app.models.schemas import ScrapeRequest, FeedStrategy, GraphQLOperation, ScrapeSelectors

    op = GraphQLOperation(
        endpoint="https://api.example.com/graphql",
        query="query Feed($limit: Int) { feed(limit: $limit) { headline permalink } }",
        variables={"limit": 10},
        response_path="data.feed",
    )
    req = ScrapeRequest(
        url="https://api.example.com/graphql",
        strategy=FeedStrategy.GRAPHQL,
        graphql=op,
        selectors=ScrapeSelectors(item_title="headline", item_link="permalink"),
    )
    resp = await run_scrape(req)
    assert resp.item_count == 1
    assert resp.items[0].title == "First"
    assert resp.errors == []


@respx.mock
async def test_graphql_bad_response_path():
    respx.post("https://api.example.com/graphql").mock(
        return_value=Response(200, json={"data": {"nothing": "here"}})
    )
    from app.scraping.scrape import run_scrape
    from app.models.schemas import ScrapeRequest, FeedStrategy, GraphQLOperation, ScrapeSelectors

    op = GraphQLOperation(
        endpoint="https://api.example.com/graphql",
        query="{ posts { title } }",
        response_path="data.posts",
    )
    req = ScrapeRequest(
        url="https://api.example.com/graphql",
        strategy=FeedStrategy.GRAPHQL,
        graphql=op,
        selectors=ScrapeSelectors(item_title="title"),
    )
    resp = await run_scrape(req)
    assert resp.item_count == 0
    assert resp.warnings  # should warn about unresolved path


@respx.mock
async def test_graphql_no_operation():
    """ScrapeRequest with no graphql field returns a warning."""
    from app.scraping.scrape import run_scrape
    from app.models.schemas import ScrapeRequest, FeedStrategy, ScrapeSelectors

    req = ScrapeRequest(
        url="https://api.example.com/graphql",
        strategy=FeedStrategy.GRAPHQL,
        selectors=ScrapeSelectors(),
    )
    resp = await run_scrape(req)
    assert resp.item_count == 0
    assert resp.warnings or resp.errors
