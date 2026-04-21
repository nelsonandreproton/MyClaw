import base64
import json
import logging
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from errors import CredentialError

if TYPE_CHECKING:
    from memory.store import MemoryStore

logger = logging.getLogger(__name__)

_PBKDF2_ITERATIONS = 480_000


class CryptoManager:
    def __init__(self, secret_key: str):
        self._secret_key = secret_key.encode()

    # ------------------------------------------------------------------
    # Low-level encrypt / decrypt
    # ------------------------------------------------------------------

    def encrypt(self, service: str, data: dict) -> bytes:
        fernet = self._fernet_for(service)
        return fernet.encrypt(json.dumps(data, ensure_ascii=False).encode())

    def decrypt(self, service: str, blob: bytes) -> dict:
        fernet = self._fernet_for(service)
        try:
            return json.loads(fernet.decrypt(blob))
        except (InvalidToken, json.JSONDecodeError) as exc:
            raise CredentialError(f"Failed to decrypt credential for '{service}'") from exc

    # ------------------------------------------------------------------
    # High-level credential helpers (use MemoryStore)
    # ------------------------------------------------------------------

    async def save_credential(self, service: str, data: dict, store: "MemoryStore") -> None:
        encrypted = self.encrypt(service, data)
        existing = await store.fetchone(
            "SELECT id FROM credentials WHERE service = ?", (service,)
        )
        if existing:
            await store.execute(
                "UPDATE credentials SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE service = ?",
                (encrypted, service),
            )
        else:
            await store.execute(
                "INSERT INTO credentials (service, data) VALUES (?, ?)",
                (service, encrypted),
            )
        logger.debug("Credential saved for service '%s'", service)

    async def get_credential(self, service: str, store: "MemoryStore") -> dict | None:
        row = await store.fetchone(
            "SELECT data FROM credentials WHERE service = ?", (service,)
        )
        if not row:
            return None
        return self.decrypt(service, bytes(row["data"]))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fernet_for(self, service: str) -> Fernet:
        # Unique 16-byte salt per service derived from its name.
        salt = service.encode().ljust(16, b"\x00")[:16]
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=_PBKDF2_ITERATIONS,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self._secret_key))
        return Fernet(key)
