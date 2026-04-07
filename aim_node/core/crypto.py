from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .config import AIMCoreConfig

logger = logging.getLogger(__name__)


class DeviceCrypto:
    """
    Manage AIM node cryptographic identity and local encrypted keystore state.
    """

    def __init__(self, config: AIMCoreConfig, passphrase: str):
        self.config = config
        self.keystore_path = Path(config.keystore_path)
        self._passphrase = passphrase.encode("utf-8")
        self._pbkdf2_iterations = 600_000

    @staticmethod
    def generate_ed25519_keypair() -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
        private_key = ed25519.Ed25519PrivateKey.generate()
        return private_key, private_key.public_key()

    @staticmethod
    def generate_x25519_keypair() -> tuple[x25519.X25519PrivateKey, x25519.X25519PublicKey]:
        private_key = x25519.X25519PrivateKey.generate()
        return private_key, private_key.public_key()

    def _derive_fernet_key(self, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self._pbkdf2_iterations,
            backend=default_backend(),
        )
        return base64.urlsafe_b64encode(kdf.derive(self._passphrase))

    def _encrypt_private_key(self, private_key: ed25519.Ed25519PrivateKey | x25519.X25519PrivateKey) -> tuple[bytes, bytes]:
        salt = os.urandom(16)
        fernet_key = self._derive_fernet_key(salt)
        raw_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return Fernet(fernet_key).encrypt(raw_bytes), salt

    def _decrypt_private_key(self, encrypted_data: bytes, salt: bytes, key_type: str):
        raw_bytes = Fernet(self._derive_fernet_key(salt)).decrypt(encrypted_data)
        if key_type == "ed25519":
            return ed25519.Ed25519PrivateKey.from_private_bytes(raw_bytes)
        if key_type == "x25519":
            return x25519.X25519PrivateKey.from_private_bytes(raw_bytes)
        raise ValueError(f"Unknown key type: {key_type}")

    def _write_keystore(self, data: dict) -> None:
        self.keystore_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(self.keystore_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            os.replace(tmp_path, self.keystore_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _read_keystore(self) -> Optional[dict]:
        if not self.keystore_path.exists():
            return None
        with self.keystore_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_keys(
        self,
        keystore: dict,
    ) -> tuple[
        ed25519.Ed25519PrivateKey,
        ed25519.Ed25519PublicKey,
        x25519.X25519PrivateKey,
        x25519.X25519PublicKey,
    ]:
        ed_pub = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(keystore["ed25519_public_key"]))
        ed_priv = self._decrypt_private_key(
            keystore["encrypted_ed25519_private_key"].encode("latin-1"),
            bytes.fromhex(keystore["ed25519_salt"]),
            "ed25519",
        )
        x_pub = x25519.X25519PublicKey.from_public_bytes(bytes.fromhex(keystore["x25519_public_key"]))
        x_priv = self._decrypt_private_key(
            keystore["encrypted_x25519_private_key"].encode("latin-1"),
            bytes.fromhex(keystore["x25519_salt"]),
            "x25519",
        )
        return ed_priv, ed_pub, x_priv, x_pub

    def _save_keys(
        self,
        ed_priv: ed25519.Ed25519PrivateKey,
        ed_pub: ed25519.Ed25519PublicKey,
        x_priv: x25519.X25519PrivateKey,
        x_pub: x25519.X25519PublicKey,
    ) -> None:
        enc_ed, ed_salt = self._encrypt_private_key(ed_priv)
        enc_x, x_salt = self._encrypt_private_key(x_priv)
        existing = self._read_keystore() or {}

        data = {
            "ed25519_public_key": ed_pub.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            ).hex(),
            "encrypted_ed25519_private_key": enc_ed.decode("latin-1"),
            "ed25519_salt": ed_salt.hex(),
            "x25519_public_key": x_pub.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            ).hex(),
            "encrypted_x25519_private_key": enc_x.decode("latin-1"),
            "x25519_salt": x_salt.hex(),
        }

        for key in ("platform_ed25519_public_key", "platform_x25519_public_key", "certificate"):
            if key in existing:
                data[key] = existing[key]

        self._write_keystore(data)
        logger.info("Keypairs saved to %s", self.keystore_path)

    def get_or_create_keypairs(
        self,
    ) -> tuple[
        ed25519.Ed25519PrivateKey,
        ed25519.Ed25519PublicKey,
        x25519.X25519PrivateKey,
        x25519.X25519PublicKey,
    ]:
        keystore = self._read_keystore()
        if keystore and "ed25519_public_key" in keystore:
            return self._load_keys(keystore)

        ed_priv, ed_pub = self.generate_ed25519_keypair()
        x_priv, x_pub = self.generate_x25519_keypair()
        self._save_keys(ed_priv, ed_pub, x_priv, x_pub)
        return ed_priv, ed_pub, x_priv, x_pub

    def get_public_keys_b64(self) -> tuple[str, str]:
        keystore = self._read_keystore()
        if not keystore:
            raise RuntimeError("Keystore not initialized; call get_or_create_keypairs() first")
        return (
            base64.b64encode(bytes.fromhex(keystore["ed25519_public_key"])).decode(),
            base64.b64encode(bytes.fromhex(keystore["x25519_public_key"])).decode(),
        )

    def store_platform_keys(
        self,
        platform_ed25519_pub: str,
        platform_x25519_pub: str,
        certificate: str,
    ) -> None:
        keystore = self._read_keystore()
        if not keystore:
            raise RuntimeError("Keystore not initialized; cannot store platform keys")
        keystore["platform_ed25519_public_key"] = platform_ed25519_pub
        keystore["platform_x25519_public_key"] = platform_x25519_pub
        keystore["certificate"] = certificate
        self._write_keystore(keystore)

    @staticmethod
    def sign(private_key: ed25519.Ed25519PrivateKey, message: bytes) -> bytes:
        return private_key.sign(message)

    @staticmethod
    def verify(public_key: ed25519.Ed25519PublicKey, message: bytes, signature: bytes) -> None:
        public_key.verify(signature, message)

    @staticmethod
    def _derive_shared_fernet_key(
        private_key: x25519.X25519PrivateKey,
        public_key: x25519.X25519PublicKey,
    ) -> bytes:
        shared_key = private_key.exchange(public_key)
        derived = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"aim-node-device-crypto",
            backend=default_backend(),
        ).derive(shared_key)
        return base64.urlsafe_b64encode(derived)

    @classmethod
    def encrypt_for_recipient(
        cls,
        sender_private_key: x25519.X25519PrivateKey,
        recipient_public_key: x25519.X25519PublicKey,
        plaintext: bytes,
    ) -> bytes:
        return Fernet(cls._derive_shared_fernet_key(sender_private_key, recipient_public_key)).encrypt(plaintext)

    @classmethod
    def decrypt_from_sender(
        cls,
        recipient_private_key: x25519.X25519PrivateKey,
        sender_public_key: x25519.X25519PublicKey,
        ciphertext: bytes,
    ) -> bytes:
        return Fernet(cls._derive_shared_fernet_key(recipient_private_key, sender_public_key)).decrypt(ciphertext)
