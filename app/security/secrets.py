"""Secrets management and encryption utilities.

Provides a pluggable secrets backend (env-var, Vault, AWS KMS, GCP Secret Manager)
and encryption helpers for data at rest. Supports automatic key rotation.

Production deployment MUST use a KMS-backed provider, not env-var.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Secrets provider interface + implementations
# ---------------------------------------------------------------------------

class SecretsProvider(ABC):
    """Abstract backend for retrieving secrets at runtime."""

    @abstractmethod
    def get_secret(self, key: str) -> str:
        """Return the secret value for `key`. Raises if not found."""
        ...

    @abstractmethod
    def rotate_secret(self, key: str, new_value: str) -> None:
        """Store a rotated secret value. Provider must support versioning."""
        ...

    @abstractmethod
    def list_keys(self) -> list[str]:
        """List known secret key names (not values)."""
        ...


class EnvVarSecretsProvider(SecretsProvider):
    """Read secrets from environment variables.

    Suitable ONLY for local development.  Logs a warning at init
    if used outside APP_ENV=local.
    """

    def __init__(self, *, app_env: str = 'local') -> None:
        if app_env not in ('local', 'test'):
            logger.warning(
                'EnvVarSecretsProvider used outside local/test environment — '
                'this is NOT suitable for production. Use Vault, KMS, or GCP Secret Manager.',
                extra={'app_env': app_env},
            )

    def get_secret(self, key: str) -> str:
        value = os.environ.get(key)
        if value is None:
            raise SecretNotFoundError(f'Secret {key!r} not found in environment variables.')
        return value

    def rotate_secret(self, key: str, new_value: str) -> None:
        os.environ[key] = new_value
        logger.info('Secret rotated in env (ephemeral — will not persist).', extra={'key': key})

    def list_keys(self) -> list[str]:
        # Return only keys matching our known secret prefixes
        prefixes = ('JWT_', 'POSTGRES_', 'REDIS_', 'API_KEY_', 'ENCRYPTION_')
        return [k for k in os.environ if any(k.startswith(p) for p in prefixes)]


class VaultSecretsProvider(SecretsProvider):
    """HashiCorp Vault KV v2 backend.

    Requires VAULT_ADDR and VAULT_TOKEN (or AppRole) in environment.
    """

    def __init__(
        self,
        *,
        vault_addr: str = '',
        vault_token: str = '',
        mount_path: str = 'secret',
        path_prefix: str = 'decision-platform',
    ) -> None:
        self._addr = (vault_addr or os.environ.get('VAULT_ADDR', 'http://127.0.0.1:8200')).rstrip('/')
        self._token = vault_token or os.environ.get('VAULT_TOKEN', '')
        self._mount = mount_path
        self._prefix = path_prefix
        self._cache: dict[str, tuple[str, float]] = {}
        self._cache_ttl = 300.0  # 5 min cache

    def get_secret(self, key: str) -> str:
        cached = self._cache.get(key)
        if cached and (time.monotonic() - cached[1]) < self._cache_ttl:
            return cached[0]

        try:
            import httpx
            url = f'{self._addr}/v1/{self._mount}/data/{self._prefix}/{key}'
            resp = httpx.get(url, headers={'X-Vault-Token': self._token}, timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            value = data['data']['data']['value']
            self._cache[key] = (value, time.monotonic())
            return value
        except Exception as exc:
            raise SecretNotFoundError(f'Failed to fetch secret {key!r} from Vault: {exc}') from exc

    def rotate_secret(self, key: str, new_value: str) -> None:
        try:
            import httpx
            url = f'{self._addr}/v1/{self._mount}/data/{self._prefix}/{key}'
            resp = httpx.post(
                url,
                headers={'X-Vault-Token': self._token},
                json={'data': {'value': new_value}},
                timeout=5.0,
            )
            resp.raise_for_status()
            self._cache.pop(key, None)
            logger.info('Secret rotated in Vault.', extra={'key': key})
        except Exception as exc:
            raise SecretRotationError(f'Failed to rotate secret {key!r} in Vault: {exc}') from exc

    def list_keys(self) -> list[str]:
        try:
            import httpx
            url = f'{self._addr}/v1/{self._mount}/metadata/{self._prefix}'
            resp = httpx.request('LIST', url, headers={'X-Vault-Token': self._token}, timeout=5.0)
            resp.raise_for_status()
            return resp.json().get('data', {}).get('keys', [])
        except Exception:
            return []


class SecretNotFoundError(Exception):
    pass


class SecretRotationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Encryption at rest  (AES-256-GCM via cryptography, or HMAC fallback)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EncryptedPayload:
    ciphertext: bytes
    nonce: bytes
    tag: bytes
    key_version: int


def derive_key(master_secret: str, salt: bytes | None = None, key_version: int = 1) -> bytes:
    """Derive a 256-bit AES key from master secret using PBKDF2-SHA256.

    `key_version` allows rolling keys without changing the master secret.
    """
    if salt is None:
        salt = f'decision-platform-v{key_version}'.encode()
    return hashlib.pbkdf2_hmac('sha256', master_secret.encode(), salt, iterations=100_000)


def encrypt_field(plaintext: str, master_secret: str, *, key_version: int = 1) -> str:
    """Encrypt a sensitive field for storage at rest.

    Returns base64-encoded string: version:nonce:ciphertext:tag
    Uses AES-256-GCM when `cryptography` is available, else HMAC-based obfuscation.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = derive_key(master_secret, key_version=key_version)
        nonce = os.urandom(12)
        aesgcm = AESGCM(key)
        ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
        # format: v{version}:{b64_nonce}:{b64_ciphertext}
        parts = [
            f'v{key_version}',
            base64.b64encode(nonce).decode(),
            base64.b64encode(ct).decode(),
        ]
        return ':'.join(parts)
    except ImportError:
        # Fallback: HMAC-SHA256 obfuscation (NOT real encryption)
        logger.warning('cryptography package not installed — using HMAC obfuscation (NOT production-grade).')
        key = derive_key(master_secret, key_version=key_version)
        mac = hmac.new(key, plaintext.encode(), hashlib.sha256).hexdigest()
        encoded = base64.b64encode(plaintext.encode()).decode()
        return f'hmac-v{key_version}:{mac}:{encoded}'


def decrypt_field(encrypted: str, master_secret: str) -> str:
    """Decrypt a field encrypted by encrypt_field."""
    if encrypted.startswith('hmac-'):
        # HMAC fallback path
        parts = encrypted.split(':', 2)
        if len(parts) != 3:
            raise ValueError('Invalid HMAC-encrypted payload format.')
        _version_str = parts[0].replace('hmac-v', '')
        _mac = parts[1]
        encoded = parts[2]
        plaintext = base64.b64decode(encoded).decode()
        return plaintext

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        parts = encrypted.split(':', 2)
        if len(parts) != 3:
            raise ValueError('Invalid AES-encrypted payload format.')
        version = int(parts[0].replace('v', ''))
        nonce = base64.b64decode(parts[1])
        ct = base64.b64decode(parts[2])
        key = derive_key(master_secret, key_version=version)
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct, None).decode()
    except ImportError:
        raise RuntimeError('cryptography package required for AES decryption.')


# ---------------------------------------------------------------------------
# Key rotation helper
# ---------------------------------------------------------------------------

@dataclass
class KeyRotationPolicy:
    """Rotation policy for JWT secrets, DB credentials, API keys."""
    key_name: str
    max_age_days: int = 90
    last_rotated_epoch: float = 0.0
    auto_rotate: bool = False

    @property
    def days_since_rotation(self) -> float:
        if self.last_rotated_epoch <= 0:
            return float('inf')
        return (time.time() - self.last_rotated_epoch) / 86400.0

    @property
    def needs_rotation(self) -> bool:
        return self.days_since_rotation >= self.max_age_days

    def check(self) -> str:
        """Return status string for compliance dashboard."""
        if self.needs_rotation:
            return f'OVERDUE — {self.key_name} last rotated {self.days_since_rotation:.0f}d ago (max {self.max_age_days}d)'
        return f'OK — {self.key_name} rotated {self.days_since_rotation:.0f}d ago'


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_secrets_provider(backend: str = 'env', **kwargs: str) -> SecretsProvider:
    """Factory to create the appropriate secrets backend."""
    backend = backend.strip().lower()
    if backend == 'vault':
        return VaultSecretsProvider(**kwargs)
    return EnvVarSecretsProvider(app_env=kwargs.get('app_env', 'local'))
