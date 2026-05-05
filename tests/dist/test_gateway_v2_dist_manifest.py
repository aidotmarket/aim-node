from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "dist" / "gateway_v2_manifest.json"
PROFILE_PATH = REPO_ROOT / "dist" / "install_profiles" / "gateway_v2.yaml"
HEALTH_TS_PATH = REPO_ROOT / "src" / "gateway_v2" / "health.ts"
REGISTRY_TS_PATH = REPO_ROOT / "src" / "gateway_v2" / "connector_registry.ts"

LOCKED_SURFACES = {
    "discover",
    "quote",
    "connect",
    "invoke",
    "meter",
    "receipt",
    "publish",
    "verify_provider",
    "request_access",
    "estimate_cost",
    "create_billing_session",
}

REQUIRED_COMPONENTS = {
    "local_runtime",
    "auth_bootstrap",
    "connector_registry",
    "update_path",
    "health_checks",
    "local_secret_storage_policy",
}

REQUIRED_HEALTH_CHECKS = {
    "backend_reachability",
    "auth_bootstrap_state",
    "connector_registry_readiness",
    "meter_buffer_status",
    "update_channel",
    "local_secret_store_availability",
}

FORBIDDEN_INSTALL_PRODUCTS = {
    "seller" + "-wrapper",
    "DASH" + "BOARD",
    "EARN" + "INGS",
    "BUYER" + "-MODE",
}


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text())


def _all_packaging_text() -> str:
    return "\n".join(
        path.read_text()
        for path in (MANIFEST_PATH, PROFILE_PATH, HEALTH_TS_PATH, REGISTRY_TS_PATH)
    )


def test_dist_manifest_packages_gateway_v2_runtime_components() -> None:
    manifest = _manifest()

    assert manifest["runtime"] == "gateway-v2"
    assert set(manifest["packaged_components"]) == REQUIRED_COMPONENTS
    assert manifest["credential_policy"] == {
        "runtime_credentials": "local_only",
        "secret_ref_prefix": "local://aim-node/secrets/",
        "committed_credentials": False,
        "test_mode_keys": "dev_fixtures_only",
    }
    assert manifest["update_path"]["channel"] == "gateway-v2-stable"


def test_install_profile_supports_buyer_local_and_seller_edge_modes() -> None:
    manifest = _manifest()
    profile = PROFILE_PATH.read_text()

    assert set(manifest["modes"]) == {"buyer_local", "seller_edge"}
    assert re.search(r"^  buyer_local:\n", profile, re.MULTILINE)
    assert re.search(r"^  seller_edge:\n", profile, re.MULTILINE)
    assert "package_boundary: aim-node-gateway-v2-runtime" in profile
    assert "gateway-v2-runtime" in profile


def test_health_checks_cover_distribution_readiness_contract() -> None:
    manifest = _manifest()
    health_ts = HEALTH_TS_PATH.read_text()

    assert set(manifest["health_checks"]) == REQUIRED_HEALTH_CHECKS
    for check_name in REQUIRED_HEALTH_CHECKS:
        assert check_name in health_ts
    assert 'runtime: "gateway-v2"' in health_ts
    assert "buyer_local" in health_ts
    assert "seller_edge" in health_ts


def test_runtime_credentials_remain_local_and_no_real_keys_are_committed() -> None:
    text = _all_packaging_text()

    assert "local://aim-node/secrets/" in text
    assert "local_only" in text
    assert "dev_fixtures_only" in text
    assert "sk-" not in text
    assert "-----BEGIN" not in text
    assert "api_key:" not in text
    assert "secret_key:" not in text


def test_locked_surface_names_are_packaged_without_old_install_products() -> None:
    manifest = _manifest()
    text = _all_packaging_text()

    assert set(manifest["surface_names"]) == LOCKED_SURFACES
    for surface in LOCKED_SURFACES:
        assert surface in text
    for forbidden_product in FORBIDDEN_INSTALL_PRODUCTS:
        assert forbidden_product not in MANIFEST_PATH.read_text()
        assert forbidden_product not in PROFILE_PATH.read_text()
    assert manifest["install_products"] == ["gateway-v2-runtime"]


def test_connector_registry_is_gateway_v2_runtime_scoped() -> None:
    registry_ts = REGISTRY_TS_PATH.read_text()

    assert "gatewayV2SurfaceNames" in registry_ts
    assert "connectorRegistryReady" in registry_ts
    assert "buyer_local" in registry_ts
    assert "seller_edge" in registry_ts
    assert "local://aim-node/secrets/" in registry_ts
    for surface in LOCKED_SURFACES:
        assert surface in registry_ts
