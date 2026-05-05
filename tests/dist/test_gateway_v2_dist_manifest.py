from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "dist" / "gateway_v2_manifest.json"
PROFILE_PATH = REPO_ROOT / "dist" / "install_profiles" / "gateway_v2.yaml"
HEALTH_TS_PATH = REPO_ROOT / "src" / "gateway_v2" / "health.ts"
REGISTRY_TS_PATH = REPO_ROOT / "src" / "gateway_v2" / "connector_registry.ts"
DIST_RELATED_SCAN_ROOTS = (
    REPO_ROOT / "dist",
    REPO_ROOT / "src" / "gateway_v2",
    REPO_ROOT / "tests" / "dist",
)

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

REAL_KEY_PATTERNS = {
    "stripe_secret_live_dash": re.compile(r"\bsk-live-[A-Za-z0-9_-]+"),
    "stripe_secret_live_underscore": re.compile(r"\bsk_live_[A-Za-z0-9_-]+"),
    "stripe_publishable_live": re.compile(r"\bpk_live_[A-Za-z0-9_-]+"),
    "bearer_high_entropy": re.compile(r"\bBearer [A-Za-z0-9]{30,}"),
    "generic_api_key_assignment": re.compile(
        r"\b(?:api_key|api-key|apikey)\b\s*[:=]\s*[\"']?[A-Za-z0-9_-]{20,}",
        re.IGNORECASE,
    ),
}


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text())


def _all_packaging_text() -> str:
    return "\n".join(
        path.read_text()
        for path in (MANIFEST_PATH, PROFILE_PATH, HEALTH_TS_PATH, REGISTRY_TS_PATH)
    )


def _is_dev_fixtures_only_allowlist(path: Path, line: str) -> bool:
    return "dev_fixtures_only" in path.parts or "dev_fixtures_only" in line


def _dist_related_text_files() -> list[Path]:
    files: list[Path] = []
    for root in DIST_RELATED_SCAN_ROOTS:
        files.extend(path for path in root.rglob("*") if path.is_file() and path.suffix != ".pyc")
    return files


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
    assert "-----BEGIN" not in text
    assert "secret_key:" not in text

    findings: list[str] = []
    for path in _dist_related_text_files():
        relative_path = path.relative_to(REPO_ROOT)
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            findings.append(f"{relative_path}: binary/unreadable file included in dist-related scan")
            continue
        for line_number, line in enumerate(lines, start=1):
            if _is_dev_fixtures_only_allowlist(path, line):
                continue
            for pattern_name, pattern in REAL_KEY_PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"{relative_path}:{line_number}: matched {pattern_name}")

    assert findings == []


def test_real_key_detection_regexes_match_obvious_patterns() -> None:
    dev_fixtures_only_positive_controls = {
        "stripe_secret_live_dash": "sk-" + "live-1234567890abcdefghijklmnop",  # dev_fixtures_only
        "stripe_secret_live_underscore": "sk_" + "live_1234567890abcdefghijklmnop",  # dev_fixtures_only
        "stripe_publishable_live": "pk_" + "live_1234567890abcdefghijklmnop",  # dev_fixtures_only
        "bearer_high_entropy": "Bearer abcdefghijklmnopqrstuvwxyzABCDE",  # dev_fixtures_only
        "generic_api_key_assignment": "api_key: abcdefghijklmnopqrst",  # dev_fixtures_only
    }

    for pattern_name, sample in dev_fixtures_only_positive_controls.items():
        assert REAL_KEY_PATTERNS[pattern_name].search(sample)


def test_locked_surface_names_are_packaged_without_old_install_products() -> None:
    manifest = _manifest()
    manifest_text = MANIFEST_PATH.read_text()
    profile_text = PROFILE_PATH.read_text()
    registry_ts = REGISTRY_TS_PATH.read_text()

    assert set(manifest["surface_names"]) == LOCKED_SURFACES
    for surface in LOCKED_SURFACES:
        assert surface in manifest_text
        assert surface in profile_text
        assert surface in registry_ts
    for forbidden_product in FORBIDDEN_INSTALL_PRODUCTS:
        assert forbidden_product not in manifest_text
        assert forbidden_product not in profile_text
        assert forbidden_product not in registry_ts
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
