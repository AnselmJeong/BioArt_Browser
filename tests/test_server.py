from fastapi.testclient import TestClient
from bioart import server


def test_http_origin_token_host_and_export(library, monkeypatch):
    monkeypatch.setattr(server, "catalog", library)
    with TestClient(server.app) as client:
        token = client.get("/api/session").json()["token"]
        assert (
            client.post("/api/export", json={"file_ids": ["2311"]}).status_code == 403
        )
        assert client.get("/api/stats", headers={"Host": "evil.com"}).status_code == 403
        headers = {"X-Bioart-Token": token, "Origin": "https://evil.com"}
        assert (
            client.post(
                "/api/export", json={"file_ids": ["2311"]}, headers=headers
            ).status_code
            == 403
        )
        headers = {"X-Bioart-Token": token}
        result = client.post(
            "/api/export", json={"file_ids": ["2311"]}, headers=headers
        )
        assert result.status_code == 200
        assert client.get(result.json()["download_url"]).status_code == 200
        assert client.get("/api/preview/782376").status_code == 400
        assert client.get("/api/exports/secret.zip").status_code == 400
        assert client.get("/api/search?q=폐").json()["total"] == 2
        assert "nosniff" in client.get("/api/stats").headers["x-content-type-options"]


def test_session_persists(library, monkeypatch):
    monkeypatch.setattr(server, "catalog", library)
    with TestClient(server.app) as client:
        token = client.get("/api/session").json()["token"]
        assert (
            client.post(
                "/api/session",
                json={"tray": ["2311"], "query": "폐"},
                headers={"X-Bioart-Token": token},
            ).status_code
            == 200
        )
        assert client.get("/api/session").json()["state"]["tray"] == ["2311"]
