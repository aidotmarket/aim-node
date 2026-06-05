from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs/gateway_v2_migration.md").read_text()
ALIASES = (ROOT / "src/cli/gateway_v2_aliases.ts").read_text()


def test_paused_bqs_have_preserved_retired_deprecated_and_replacement_content() -> None:
    for bq in ("DASHBOARD", "EARNINGS", "BUYER-MODE"):
        section = DOC.split(f"## {bq}", 1)[1].split("## ", 1)[0]
        assert "Preserved" in section or "Preserved content" in section
        assert "Retired content" in section
        assert "Deprecated names and replacements" in section
        assert "Replacement" in section


def test_dashboard_migration_carries_required_console_content_without_secrets() -> None:
    section = DOC.split("## DASHBOARD", 1)[1].split("## EARNINGS", 1)[0]
    for required in (
        "Connector/provider health",
        "Local credential visibility without secrets",
        "Invocation logs",
        "Usage counters",
        "Receipt lookup",
        "Local runtime status",
        "standalone dashboard strategy is retired",
        "Marketplace admin scope is retired",
    ):
        assert required in section
    assert "Raw credentials or secrets are never displayed" in section


def test_earnings_migration_is_read_only_and_removes_local_balance() -> None:
    section = DOC.split("## EARNINGS", 1)[1].split("## BUYER-MODE", 1)[0]
    for required in (
        "Seller billable usage",
        "Transaction receipts",
        "Payout references",
        "Revenue attribution by listing/version",
        "read-only backend-derived",
        "AIM-Node local balance calculation is removed",
        "balance_ledger",
    ):
        assert required in section


def test_buyer_mode_migration_carries_gateway_flow_and_retires_generic_mode() -> None:
    section = DOC.split("## BUYER-MODE", 1)[1].split("## Compatibility Rules", 1)[0]
    for required in (
        "gateway.discover",
        "gateway.verifyProvider",
        "gateway.estimateCost",
        "gateway.quote.create",
        "gateway.quote.get",
        "gateway.requestAccess",
        "gateway.createBillingSession",
        "gateway.connect",
        "gateway.invoke",
        "gateway.receipt.get",
        "gateway.receipt.lookup",
        "Generic buyer mode is retired",
        "Local-only purchase state is removed",
    ):
        assert required in section


def test_command_aliases_use_locked_gateway_v2_surfaces() -> None:
    for surface in (
        '"discover"',
        '"quote.create"',
        '"connect"',
        '"invoke"',
        '"meter.list"',
        '"receipt.get"',
        '"receipt.lookup"',
        '"verify_provider"',
        '"request_access"',
        '"estimate_cost"',
        '"create_billing_session"',
    ):
        assert surface in ALIASES

    for deprecated_name in (
        "aim-node dashboard",
        "aim-node earnings",
        "aim-node buyer discover",
        "aim-node buyer verify",
        "aim-node buyer estimate",
        "aim-node buyer quote",
        "aim-node buyer access",
        "aim-node buyer billing",
        "aim-node buyer connect",
        "aim-node buyer invoke",
        "aim-node buyer receipt",
    ):
        assert deprecated_name in ALIASES
        assert "deprecated" in ALIASES


def test_removed_aliases_have_explicit_user_facing_messages() -> None:
    for removed in ("aim-node balance", "aim-node buyer buy-and-run"):
        assert removed in ALIASES
    assert "removed: AIM-Node local balance calculation is retired" in ALIASES
    assert "removed: combined discover + payment + invoke aliases are rejected" in ALIASES


def test_rejects_any_alias_combining_discover_payment_and_invoke() -> None:
    assert "removedCombinedGatewayV2Aliases" in ALIASES
    assert "aim-node buyer buy-and-run" in ALIASES
    assert "gateway.buyer.purchaseAndInvoke" in ALIASES
    assert "must not combine discover + payment + invoke" in ALIASES
    assert "run discover, quote, billing, connect, invoke, and receipt separately" in ALIASES


def test_sdk_rename_or_removal_is_documented() -> None:
    for sdk_mapping in (
        "gateway.buyer.discover",
        "gateway.buyer.verifyProvider",
        "gateway.buyer.estimateCost",
        "gateway.buyer.requestAccess",
        "gateway.buyer.createBillingSession",
        "gateway.buyer.purchaseAndInvoke",
        "gateway.earnings.summary",
        "gateway.discover",
        "gateway.verifyProvider",
        "gateway.estimateCost",
        "gateway.requestAccess",
        "gateway.createBillingSession",
    ):
        assert sdk_mapping in DOC
