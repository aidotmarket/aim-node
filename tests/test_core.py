from __future__ import annotations

import json
import logging
from pathlib import Path

from cryptography.exceptions import InvalidSignature

from aim_node.core.config import AIMCoreConfig
from aim_node.core.crypto import DeviceCrypto
from aim_node.core.logging import setup_logging
from aim_node.core.offline_queue import OfflineQueue


def test_config_defaults(tmp_path: Path) -> None:
    config = AIMCoreConfig(keystore_path=tmp_path / "keystore.json", node_serial="node-123")

    assert config.market_api_url == "https://api.ai.market"
    assert config.market_ws_url == "wss://api.ai.market/ws"
    assert config.reconnect_delay_s == 5.0
    assert config.reconnect_max_delay_s == 60.0
    assert config.reconnect_jitter == 0.3
    assert config.api_key is None


def test_config_custom_paths(tmp_path: Path) -> None:
    config = AIMCoreConfig(
        keystore_path=tmp_path / "keys" / "device.json",
        node_serial="node-custom",
        data_dir=tmp_path / "state",
    )

    assert config.keystore_path == tmp_path / "keys" / "device.json"
    assert config.data_dir == tmp_path / "state"
    assert config.node_serial == "node-custom"


def test_crypto_keypair_generate(core_config: AIMCoreConfig) -> None:
    crypto = DeviceCrypto(core_config, passphrase="secret")

    ed_priv, ed_pub, x_priv, x_pub = crypto.get_or_create_keypairs()

    assert core_config.keystore_path.exists()
    assert ed_priv.public_key().public_bytes_raw() == ed_pub.public_bytes_raw()
    assert x_priv.public_key().public_bytes_raw() == x_pub.public_bytes_raw()


def test_crypto_sign_verify(core_config: AIMCoreConfig) -> None:
    crypto = DeviceCrypto(core_config, passphrase="secret")
    ed_priv, ed_pub, _, _ = crypto.get_or_create_keypairs()
    payload = b"hello aim-node"

    signature = crypto.sign(ed_priv, payload)

    crypto.verify(ed_pub, payload, signature)

    try:
        crypto.verify(ed_pub, b"tampered", signature)
    except InvalidSignature:
        pass
    else:
        raise AssertionError("expected signature verification failure")


def test_crypto_encrypt_decrypt(core_config: AIMCoreConfig) -> None:
    crypto = DeviceCrypto(core_config, passphrase="secret")
    _, _, sender_private, sender_public = crypto.get_or_create_keypairs()
    recipient_private, recipient_public = crypto.generate_x25519_keypair()
    plaintext = b"encrypted payload"

    ciphertext = crypto.encrypt_for_recipient(sender_private, recipient_public, plaintext)
    decrypted = crypto.decrypt_from_sender(recipient_private, sender_public, ciphertext)

    assert decrypted == plaintext
    assert ciphertext != plaintext


def test_logging_setup(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir, log_file="aim-node.jsonl", log_level=logging.DEBUG)
    logger = logging.getLogger("aim_node.test")

    logger.info("test log event")

    log_path = log_dir / "aim-node.jsonl"
    assert log_path.exists()
    payload = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert payload["event"] == "test log event"
    assert payload["service"] == "aim-node"


def test_offline_queue_enqueue_dequeue(core_config: AIMCoreConfig) -> None:
    queue = OfflineQueue(core_config)
    entry = {"request_id": "req-1", "cost_usd": "1.00", "category": "setup"}

    appended = queue.append(entry)
    dequeued = queue.dequeue_all()

    assert appended is True
    assert dequeued == [entry]
    assert queue.count() == 0


def test_offline_queue_persistence(core_config: AIMCoreConfig) -> None:
    first = OfflineQueue(core_config)
    second = OfflineQueue(core_config)
    entries = [
        {"request_id": "req-1", "cost_usd": "1.00"},
        {"request_id": "req-2", "cost_usd": "2.00"},
    ]

    for entry in entries:
        assert first.append(entry) is True

    assert second.read_all() == entries
    assert second.path == core_config.data_dir / "pending_usage.jsonl"
