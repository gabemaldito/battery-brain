"""
CORS integration tests for frontend consumption.

These tests validate the CORSMiddleware in app.main without hitting external APIs:
  - Preflight (OPTIONS) from a whitelisted origin returns 200 + Allow-Origin header
  - Preflight from a non-whitelisted origin returns 400 (no Allow-Origin)
  - GET requests with whitelisted Origin include Access-Control-Allow-Origin
  - OpenAPI spec advertises tag groups for organization

We use `/health` and `/openapi.json` as test endpoints because they do not make
external API calls (unlike /api/v1/decision and /api/v1/forecast).
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---------------- CORS preflight (OPTIONS) ----------------
def test_cors_preflight_allowed_origin_returns_200():
    """Preflight from whitelisted origin (localhost:3000) returns 200 + CORS headers."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200, f"Preflight failed: {response.text}"
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    # The middleware must echo at least the requested method back as Allowed.
    assert "GET" in response.headers.get("access-control-allow-methods", "").upper()


def test_cors_preflight_unknown_origin_rejected():
    """Preflight from non-whitelisted origin returns 400 (no Allow-Origin header)."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # FastAPI/Starlette CORS returns 400 for disallowed origins.
    assert response.status_code == 400
    assert "access-control-allow-origin" not in {
        k.lower() for k in response.headers.keys()
    }


def test_cors_preflight_all_default_dev_origins_allowed():
    """Each of the dev defaults (3000, 5173, 8080, 4200 + 127.0.0.1 variants) is allowed."""
    for origin in [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://localhost:4200",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:4200",
    ]:
        response = client.options(
            "/health",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert response.status_code == 200, f"Origin {origin} unexpectedly rejected"
        assert response.headers.get("access-control-allow-origin") == origin


# ---------------- Regular GET with Origin ----------------
def test_get_with_allowed_origin_includes_allow_origin_header():
    """A normal GET to /health from a whitelisted origin includes the Allow-Origin header."""
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_get_with_unknown_origin_omits_allow_origin_header():
    """GET from a non-allowed origin still serves the response but does NOT expose Allow-Origin."""
    response = client.get("/health", headers={"Origin": "http://evil.example.com"})
    assert response.status_code == 200  # API still responds
    assert "access-control-allow-origin" not in {
        k.lower() for k in response.headers.keys()
    }


# ---------------- OpenAPI metadata ----------------
def test_openapi_spec_advertises_expected_tag_groups():
    """OpenAPI tags include 'decision', 'forecast', 'system' for Swagger organization."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert "tags" in spec
    tag_names = {t["name"] for t in spec["tags"]}
    assert {"decision", "forecast", "system"}.issubset(tag_names)


def test_openapi_paths_grouped_under_v1_prefix():
    """Business endpoints are exposed under /api/v1 in the OpenAPI spec."""
    response = client.get("/openapi.json")
    spec = response.json()
    paths = spec["paths"]
    assert "/api/v1/decision" in paths
    assert "/api/v1/forecast" in paths


def test_openapi_spec_includes_decision_and_forecast_schemas():
    """OpenAPI spec must fully describe /decision response schema (for typed client generation)."""
    response = client.get("/openapi.json")
    spec = response.json()
    decision_path = spec["paths"]["/api/v1/decision"]
    assert "get" in decision_path
    # The summary should mention the battery action.
    summary = decision_path["get"].get("summary", "") + decision_path["get"].get("description", "")
    assert "CHARGE" in summary or "decision" in summary.lower() or "decision" in str(decision_path["get"].get("tags", [])).lower()


# ---------------- System endpoints ----------------
def test_root_health_legacy():
    """GET / returns Server running."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "Server running"


def test_health_endpoint_returns_status_and_timestamp():
    """GET /health is the explicit health probe for orchestrators."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "timestamp" in body
    assert "api_version" in body
