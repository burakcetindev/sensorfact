"""Tests for the FastAPI application layer (main.py).

All tests use httpx's ASGI transport so no real server is needed.
GraphQL introspection queries are used where possible — they exercise the
full request path without touching the blockchain service.
"""
from __future__ import annotations

import json

import httpx
import pytest

from src.main import app


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
async def client():
    """Yield an async test client backed by the ASGI app."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:

    @pytest.mark.asyncio
    async def test_returns_200(self, client):
        """GET /health returns 200."""
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_status_ok(self, client):
        """Body is {"status": "ok"}."""
        response = await client.get("/health")
        assert response.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_content_type_json(self, client):
        """Response has JSON content-type."""
        response = await client.get("/health")
        assert "application/json" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# GET /graphql  (GraphiQL UI)
# ---------------------------------------------------------------------------

class TestGraphiQLEndpoint:

    @pytest.mark.asyncio
    async def test_returns_200(self, client):
        """GET /graphql returns 200 HTML."""
        response = await client.get("/graphql")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_content_type_html(self, client):
        """Response is HTML."""
        response = await client.get("/graphql")
        assert "text/html" in response.headers["content-type"]

    @pytest.mark.asyncio
    async def test_body_contains_graphiql(self, client):
        """HTML body references the GraphiQL library."""
        response = await client.get("/graphql")
        assert "graphiql" in response.text.lower()

    @pytest.mark.asyncio
    async def test_body_contains_title(self, client):
        """HTML body has the expected page title."""
        response = await client.get("/graphql")
        assert "Bitcoin Energy API" in response.text


# ---------------------------------------------------------------------------
# POST /graphql  (GraphQL execution)
# ---------------------------------------------------------------------------

class TestGraphQLEndpoint:

    @pytest.mark.asyncio
    async def test_introspection_returns_200(self, client):
        """A schema introspection query executes and returns 200."""
        response = await client.post(
            "/graphql",
            json={"query": "{ __schema { queryType { name } } }"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_introspection_returns_data(self, client):
        """Introspection result contains 'data' with the schema root type."""
        response = await client.post(
            "/graphql",
            json={"query": "{ __schema { queryType { name } } }"},
        )
        body = response.json()
        assert "data" in body
        assert body["data"]["__schema"]["queryType"]["name"] == "Query"

    @pytest.mark.asyncio
    async def test_no_errors_on_introspection(self, client):
        """Introspection produces no errors array."""
        response = await client.post(
            "/graphql",
            json={"query": "{ __schema { queryType { name } } }"},
        )
        body = response.json()
        assert "errors" not in body

    @pytest.mark.asyncio
    async def test_invalid_query_returns_400_with_errors(self, client):
        """An invalid GraphQL query (unknown field) returns 400 with an errors array."""
        response = await client.post(
            "/graphql",
            json={"query": "{ nonExistentField }"},
        )
        assert response.status_code == 400
        body = response.json()
        assert "errors" in body

    @pytest.mark.asyncio
    async def test_content_type_json(self, client):
        """GraphQL responses always have JSON content-type."""
        response = await client.post(
            "/graphql",
            json={"query": "{ __schema { queryType { name } } }"},
        )
        assert "application/json" in response.headers["content-type"]

    @pytest.mark.asyncio
    async def test_malformed_json_returns_400(self, client):
        """Sending a non-JSON body returns 400 with a structured GraphQL error."""
        response = await client.post(
            "/graphql",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        body = response.json()
        assert "errors" in body

    @pytest.mark.asyncio
    async def test_type_introspection(self, client):
        """Query schema types to confirm our custom SDL types are present."""
        response = await client.post(
            "/graphql",
            json={"query": "{ __schema { types { name } } }"},
        )
        body = response.json()
        type_names = [t["name"] for t in body["data"]["__schema"]["types"]]
        assert "BlockEnergySummary" in type_names
        assert "DailyEnergySummary" in type_names
        assert "WalletEnergySummary" in type_names

    @pytest.mark.asyncio
    async def test_cors_headers_present(self, client):
        """CORS middleware must allow any origin."""
        response = await client.get(
            "/health",
            headers={"Origin": "http://example.com"},
        )
        assert response.headers.get("access-control-allow-origin") == "*"
