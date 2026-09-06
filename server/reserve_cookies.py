"""
Reserve cookies management module.
Handles crowdsourced cloud cookies pool persistence, deduplication, and auth gating.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import ServerConfig
    from .storage import CloudStorage

logger = logging.getLogger(__name__)

DEFAULT_RESERVE_COOKIES_PATH = Path.home() / ".gamdl" / "reserve_cookies.json"
RESERVE_COOKIES_S3_KEY = "_config/reserve_cookies.json"


class ReserveCookiesManager:
    """Manages pool of reserve Apple Music accounts (cookies)."""

    def __init__(
        self,
        cloud_storage: CloudStorage | None = None,
        local_path: Path = DEFAULT_RESERVE_COOKIES_PATH,
    ):
        self.cloud_storage = cloud_storage
        self.local_path = local_path
        self._lock = threading.Lock()
        self._accounts: list[dict[str, Any]] = []

    def _load(self) -> None:
        """Load reserve accounts from Cloudflare R2 or local disk."""
        with self._lock:
            if self.cloud_storage and self.cloud_storage.bucket:
                try:
                    resp = self.cloud_storage.s3.get_object(
                        Bucket=self.cloud_storage.bucket,
                        Key=RESERVE_COOKIES_S3_KEY,
                    )
                    raw = resp["Body"].read().decode("utf-8")
                    self._accounts = json.loads(raw)
                    logger.info("Loaded %d reserve accounts from cloud storage", len(self._accounts))
                    return
                except Exception as e:
                    logger.info("No reserve cookies in cloud storage or failed to load: %s", e)
                    self._accounts = []
                    return

            if self.local_path.exists():
                try:
                    self._accounts = json.loads(self.local_path.read_text(encoding="utf-8"))
                    logger.info("Loaded %d reserve accounts from local file", len(self._accounts))
                except Exception as e:
                    logger.warning("Failed to load local reserve cookies from %s: %s", self.local_path, e)
                    self._accounts = []
            else:
                self._accounts = []

    def _save(self) -> None:
        """Persist reserve accounts to Cloudflare R2 or local disk. Must be called within self._lock."""
        if self.cloud_storage and self.cloud_storage.bucket:
            try:
                data = json.dumps(self._accounts, indent=2, ensure_ascii=False)
                self.cloud_storage.s3.put_object(
                    Bucket=self.cloud_storage.bucket,
                    Key=RESERVE_COOKIES_S3_KEY,
                    Body=data.encode("utf-8"),
                    ContentType="application/json",
                )
                logger.info("Saved %d reserve accounts to cloud storage", len(self._accounts))
                return
            except Exception as e:
                logger.error("Failed to save reserve cookies to cloud storage: %s", e)
                return

        try:
            self.local_path.parent.mkdir(parents=True, exist_ok=True)
            self.local_path.write_text(
                json.dumps(self._accounts, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Saved %d reserve accounts to %s", len(self._accounts), self.local_path)
        except Exception as e:
            logger.error("Failed to save local reserve cookies to %s: %s", self.local_path, e)

    def verify_passcode(self, passcode: str, config: ServerConfig | None = None) -> bool:
        """Verify the given passcode against configured reserve_cookies_passcode."""
        if not passcode:
            return False
        expected = getattr(config, "reserve_cookies_passcode", "amdlxd@1231996") if config else "amdlxd@1231996"
        return hmac.compare_digest(passcode.strip(), expected.strip())

    def contribute(
        self,
        token: str,
        storefront: str = "unknown",
        has_subscription: bool = False,
    ) -> dict[str, Any]:
        """Add or update an account in the reserve pool. Deduplicated by token SHA-256 hash."""
        token_clean = token.strip()
        if not token_clean:
            return {"id": "", "storefront": storefront, "is_new": False}

        token_hash = hashlib.sha256(token_clean.encode()).hexdigest()
        account_id = token_hash[:8]
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock:
            # Check for existing account
            for acc in self._accounts:
                if acc.get("token_hash") == token_hash or acc.get("id") == account_id:
                    acc["last_active"] = now_iso
                    acc["token"] = token_clean
                    if storefront and storefront != "unknown":
                        acc["storefront"] = storefront
                    acc["has_subscription"] = has_subscription
                    self._save()
                    logger.info("Updated existing reserve account %s (%s)", account_id, acc["storefront"])
                    return {"id": account_id, "storefront": acc["storefront"], "is_new": False}

            # Add new account
            entry = {
                "id": account_id,
                "token_hash": token_hash,
                "token": token_clean,
                "storefront": storefront or "unknown",
                "has_subscription": bool(has_subscription),
                "contributed_at": now_iso,
                "last_active": now_iso,
            }
            self._accounts.append(entry)
            self._save()
            logger.info("Added new reserve account %s (%s)", account_id, entry["storefront"])
            return {"id": account_id, "storefront": entry["storefront"], "is_new": True}

    def list_accounts(self) -> list[dict[str, Any]]:
        """Return list of reserve accounts with metadata only — NEVER raw tokens."""
        with self._lock:
            return [
                {
                    "id": acc["id"],
                    "storefront": acc.get("storefront", "unknown"),
                    "has_subscription": acc.get("has_subscription", False),
                    "contributed_at": acc.get("contributed_at", ""),
                    "last_active": acc.get("last_active", ""),
                }
                for acc in self._accounts
            ]

    def get_token_by_id(self, account_id: str) -> str | None:
        """Internal lookup for raw token by account_id. Never expose directly to list endpoints."""
        with self._lock:
            for acc in self._accounts:
                if acc.get("id") == account_id:
                    return acc.get("token")
            return None

    def update_account_status(
        self,
        account_id: str,
        storefront: str | None = None,
        has_subscription: bool | None = None,
    ) -> None:
        """Update last_active timestamp and optionally metadata when account is used/connected."""
        with self._lock:
            now_iso = datetime.now(timezone.utc).isoformat()
            for acc in self._accounts:
                if acc.get("id") == account_id:
                    acc["last_active"] = now_iso
                    if storefront:
                        acc["storefront"] = storefront
                    if has_subscription is not None:
                        acc["has_subscription"] = has_subscription
                    self._save()
                    break

    def delete_account(self, account_id: str) -> bool:
        """Remove an account from the pool by ID."""
        with self._lock:
            orig_len = len(self._accounts)
            self._accounts = [acc for acc in self._accounts if acc.get("id") != account_id]
            if len(self._accounts) < orig_len:
                self._save()
                logger.info("Deleted reserve account %s", account_id)
                return True
            return False
