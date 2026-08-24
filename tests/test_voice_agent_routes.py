from apps.voice_agent.server import app


def test_voice_agent_exposes_browser_routes():
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/health" in paths
    assert "/browser/voice" in paths
    assert "/browser/{session_id}/utterance" in paths
    assert "/text/start" in paths
    assert "/text/{session_id}/turn" in paths
