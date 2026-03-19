"""ORACLE cryptographic signing — Ed25519."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class CryptoEngine:
    """Ed25519 cryptographic signing engine for ORACLE."""

    def __init__(self, key_path: Optional[Path] = None):
        self.key_path = key_path
        self._private_key: Optional[Ed25519PrivateKey] = None
        self._public_key: Optional[Ed25519PublicKey] = None

        if key_path and key_path.exists():
            self._load_keys()
        else:
            self._generate_keys()
            if key_path:
                self._save_keys()

    def _generate_keys(self) -> None:
        self._private_key = Ed25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()

    def _save_keys(self) -> None:
        if not self.key_path or not self._private_key:
            return
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        private_bytes = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self.key_path.write_bytes(private_bytes)
        os.chmod(self.key_path, 0o600)
        public_path = self.key_path.with_suffix(".pub")
        public_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        public_path.write_bytes(public_bytes)

    def _load_keys(self) -> None:
        if not self.key_path:
            return
        private_bytes = self.key_path.read_bytes()
        self._private_key = serialization.load_pem_private_key(
            private_bytes, password=None
        )
        self._public_key = self._private_key.public_key()

    def sign(self, data: bytes) -> bytes:
        if not self._private_key:
            raise RuntimeError("No private key available")
        return self._private_key.sign(data)

    def verify(self, data: bytes, signature: bytes) -> bool:
        if not self._public_key:
            raise RuntimeError("No public key available")
        try:
            self._public_key.verify(signature, data)
            return True
        except Exception:
            return False

    def sign_json(self, obj: Any) -> tuple[str, str]:
        canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
        signature = self.sign(canonical.encode())
        return canonical, signature.hex()

    def verify_json(self, json_str: str, signature_hex: str) -> bool:
        return self.verify(json_str.encode(), bytes.fromhex(signature_hex))

    def get_public_key_hex(self) -> str:
        if not self._public_key:
            raise RuntimeError("No public key available")
        raw = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return raw.hex()

    @staticmethod
    def hash_data(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def hash_chain(previous_hash: str, data: bytes) -> str:
        combined = previous_hash.encode() + data
        return hashlib.sha256(combined).hexdigest()
