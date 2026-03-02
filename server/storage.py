"""
Cloud object storage client (Cloudflare R2 / S3-compatible).
Handles file uploads, signed download URLs, and cleanup.
"""

import hashlib
import logging
from pathlib import Path

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)


class CloudStorage:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str):
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
        )
        self.bucket = bucket

    @staticmethod
    def hash_token(token: str) -> str:
        """Hash user token to create a safe, unique prefix for file isolation."""
        return hashlib.sha256(token.encode()).hexdigest()[:16]

    def object_key(self, user_token: str, job_id: str, filename: str) -> str:
        """Build an R2 object key: {hashed_token}/{job_id}/{filename}."""
        prefix = self.hash_token(user_token)
        return f"{prefix}/{job_id}/{filename}"

    def upload_file(self, local_path: str | Path, object_key: str) -> str:
        """Upload a local file to R2. Returns the object key."""
        self.s3.upload_file(str(local_path), self.bucket, object_key)
        logger.info(f"Uploaded {local_path} → s3://{self.bucket}/{object_key}")
        return object_key

    def get_signed_url(self, object_key: str, expires: int = 3600) -> str:
        """Generate a pre-signed download URL (default 1 hour expiry)."""
        url = self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=expires,
        )
        return url

    def delete_object(self, object_key: str) -> None:
        """Delete a single object from R2."""
        self.s3.delete_object(Bucket=self.bucket, Key=object_key)
        logger.info(f"Deleted s3://{self.bucket}/{object_key}")

    def delete_prefix(self, prefix: str) -> int:
        """Delete all objects under a given prefix. Returns count deleted."""
        paginator = self.s3.get_paginator("list_objects_v2")
        count = 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                self.s3.delete_object(Bucket=self.bucket, Key=obj["Key"])
                count += 1
        logger.info(f"Deleted {count} objects under prefix '{prefix}'")
        return count
