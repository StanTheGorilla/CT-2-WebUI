import pytest
from httpx import AsyncClient, ASGITransport
from ct1.server.api import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_endpoint(client):
    r = await client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "brain" in data
    assert "minds" in data


@pytest.mark.asyncio
async def test_journal_endpoint(client):
    r = await client.get("/api/journal")
    assert r.status_code == 200
    data = r.json()
    assert "entries" in data
    assert "stats" in data


@pytest.mark.asyncio
async def test_sessions_endpoint(client):
    r = await client.get("/api/sessions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_config_endpoint(client):
    r = await client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert "models" in data
    assert "deliberation" in data
