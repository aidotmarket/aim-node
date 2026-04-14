from types import SimpleNamespace

from aim_node.management.allai import _safe_status_context


def test_safe_status_context_includes_current_step_and_mode():
    status = {
        "healthy": True,
        "setup_complete": False,
        "locked": True,
        "provider_running": False,
        "node_id": "node-123",
        "current_step": 3,
        "mode": "consumer",
    }
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                store=SimpleNamespace(get_dashboard=lambda: {"provider_running": False})
            )
        )
    )

    context = _safe_status_context(status, request)

    assert context["current_step"] == 3
    assert context["mode"] == "consumer"
