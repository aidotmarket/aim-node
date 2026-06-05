from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTES = (ROOT / "src/ui/gateway_console/routes.ts").read_text()


def test_gateway_console_routes_have_future_build_header() -> None:
    assert ROUTES.startswith("// FUTURE-BUILD ARTIFACT")
    assert "BQ-AIM-NODE-GATEWAY-V2-TYPESCRIPT-BUILD-PIPELINE" in ROUTES


def test_canonical_gateway_console_routes_cover_subsumed_content() -> None:
    for route in (
        "/gateway/console",
        "/gateway/console/discover",
        "/gateway/console/provider-verification",
        "/gateway/console/quotes",
        "/gateway/console/access",
        "/gateway/console/billing",
        "/gateway/console/connections",
        "/gateway/console/invocations",
        "/gateway/console/usage",
        "/gateway/console/receipts",
        "/gateway/console/revenue",
    ):
        assert route in ROUTES

    for content in (
        "connector health",
        "local credential refs without secrets",
        "invocation logs",
        "usage counters",
        "receipt lookup",
        "local runtime status",
        "Read-only seller billable usage",
        "payout references",
        "settlement references",
        "revenue attribution by listing/version",
    ):
        assert content in ROUTES


def test_deprecated_dashboard_earnings_and_buyer_routes_redirect_to_console() -> None:
    expected_redirects = {
        "/dashboard": "/gateway/console",
        "/dashboard/receipts": "/gateway/console/receipts",
        "/earnings": "/gateway/console/revenue",
        "/buyer": "/gateway/console/discover",
        "/buyer-mode": "/gateway/console/discover",
        "/buyer/checkout": "/gateway/console/billing",
        "/buyer/sessions": "/gateway/console/invocations",
    }
    for source, target in expected_redirects.items():
        assert f'path: "{source}"' in ROUTES
        assert f'replacementPath: "{target}"' in ROUTES

    assert ROUTES.count('status: "deprecated_redirect"') >= len(expected_redirects)
    assert "deprecated: DASHBOARD is subsumed by Gateway Console" in ROUTES
    assert "deprecated: EARNINGS is a read-only backend-derived Gateway Console view" in ROUTES
    assert "deprecated: generic BUYER-MODE is replaced by Gateway V2 workflow routes" in ROUTES


def test_removed_combined_buyer_route_has_explicit_message() -> None:
    assert 'path: "/buyer/buy-and-run"' in ROUTES
    assert 'status: "removed"' in ROUTES
    assert "combined discover + payment + invoke UI routes are rejected" in ROUTES
    assert "separate discover, quote, billing, connect, invoke, and receipt routes" in ROUTES


def test_routes_reference_locked_surface_method_names() -> None:
    for method in (
        "gateway.discover",
        "gateway.verifyProvider",
        "gateway.quote.create",
        "gateway.quote.get",
        "gateway.requestAccess",
        "gateway.createBillingSession",
        "gateway.connect",
        "gateway.invoke",
        "gateway.meter.list",
        "gateway.receipt.lookup",
        "gateway.receipt.get",
    ):
        assert method in ROUTES
