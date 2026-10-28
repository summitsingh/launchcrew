"""Validation errors must not echo raw user input, secrets, ctx, or input."""
import json


SECRET = "SYNTHETIC_SECRET_PROBE_98765"


def _detail_keys(body):
    detail = body.get("detail")
    assert isinstance(detail, list), body
    assert detail, body
    for entry in detail:
        assert set(entry.keys()) == {"loc", "msg", "type"}, entry
    return detail


def test_agent_validation_does_not_echo_input(client):
    response = client.post(
        "/api/agents",
        json={"name": SECRET, "role": 123, "department": "X"},
    )
    assert response.status_code == 422
    body = response.json()
    assert SECRET not in response.text
    assert '"ctx"' not in response.text
    assert '"input"' not in response.text
    _detail_keys(body)


def test_run_validation_does_not_echo_long_input(client):
    long_idea = "SYNTHETIC_LONG_" + "x" * 2000
    response = client.post(
        "/api/runs",
        json={"idea": long_idea, "agent_name": "Maker"},
    )
    assert response.status_code == 422
    body = response.json()
    assert long_idea not in response.text
    assert '"ctx"' not in response.text
    assert '"input"' not in response.text
    _detail_keys(body)


def test_run_validation_with_secret_like_value(client):
    response = client.post(
        "/api/runs",
        json={"idea": SECRET, "agent_name": "Maker", "seed_unverified_claim": "not-a-bool"},
    )
    assert response.status_code == 422
    assert SECRET not in response.text
    assert '"ctx"' not in response.text
    assert '"input"' not in response.text
    _detail_keys(response.json())
