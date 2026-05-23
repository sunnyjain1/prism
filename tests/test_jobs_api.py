from services.search_service import SearchService
from test_api_integration import auth_headers, register_user


def test_search_reindex_runs_as_background_job(api_client, monkeypatch):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])

    monkeypatch.setattr(SearchService, "is_available", lambda self: True)
    monkeypatch.setattr(SearchService, "reindex_all", lambda self, user_id, db=None: 7)

    response = api_client.post("/api/v1/search/reindex", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["name"] == "reindex_search"
    assert payload["status"] == "completed"
    assert payload["result"]["indexed_count"] == 7
    assert payload["result"]["backend"] == "meilisearch"

    detail_response = api_client.get(f"/api/v1/jobs/{payload['id']}", headers=headers)
    assert detail_response.status_code == 200, detail_response.text
    assert detail_response.json()["result"]["message"] == "Reindexed 7 transactions"

    jobs_response = api_client.get("/api/v1/jobs", headers=headers)
    assert jobs_response.status_code == 200, jobs_response.text
    assert [job["id"] for job in jobs_response.json()] == [payload["id"]]
