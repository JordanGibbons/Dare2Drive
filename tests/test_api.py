"""Tests for the FastAPI API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestHealthEndpoint:
    """Test the health check endpoint without a live database."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        from httpx import ASGITransport, AsyncClient

        from api.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestCardRoutes:
    """Test card API routes with mocked database."""

    @pytest.mark.asyncio
    async def test_list_cards_endpoint_exists(self):
        from httpx import ASGITransport, AsyncClient

        from api.main import app

        # Mock the database dependency
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        async def mock_get_session():
            yield mock_session

        from db.session import get_session

        app.dependency_overrides[get_session] = mock_get_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/cards/")

        assert resp.status_code == 200
        assert resp.json() == []
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_get_card_invalid_id(self):
        from httpx import ASGITransport, AsyncClient

        from api.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/cards/not-a-uuid")
        assert resp.status_code == 400


class TestUserRoutes:
    @pytest.mark.asyncio
    async def test_list_users_endpoint(self):
        from httpx import ASGITransport, AsyncClient

        from api.main import app

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        async def mock_get_session():
            yield mock_session

        from db.session import get_session

        app.dependency_overrides[get_session] = mock_get_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/users/")

        assert resp.status_code == 200
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_get_user_not_found(self):
        from httpx import ASGITransport, AsyncClient

        from api.main import app

        mock_session = AsyncMock()
        mock_session.get.return_value = None

        async def mock_get_session():
            yield mock_session

        from db.session import get_session

        app.dependency_overrides[get_session] = mock_get_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/users/nonexistent")

        assert resp.status_code == 404
        app.dependency_overrides.clear()


class TestRaceRoutes:
    @pytest.mark.asyncio
    async def test_list_races_endpoint(self):
        from httpx import ASGITransport, AsyncClient

        from api.main import app

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        async def mock_get_session():
            yield mock_session

        from db.session import get_session

        app.dependency_overrides[get_session] = mock_get_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/races/")

        assert resp.status_code == 200
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_get_race_invalid_id(self):
        from httpx import ASGITransport, AsyncClient

        from api.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/races/not-a-uuid")
        assert resp.status_code == 400
