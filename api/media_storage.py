"""Media storage bucket resolution: logical identity vs physical GCS storage.

This module separates the historical/logical bucket identity (used in DB audit
records, approval snapshots, and publication manifests) from the physical
GCS storage bucket used for actual network read and write operations.
"""
import os
import re

LOGICAL_MEDIA_BUCKET = 'popcorn-ai-product-media-045e861b'
STORAGE_ENV_VAR = 'POPCORN_MEDIA_STORAGE_BUCKET'

# GCS bucket naming rules: 3-63 characters, lowercase letters, numbers, hyphens, underscores, dots.
# Must begin and end with an alphanumeric character.
_BUCKET_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_.-]{1,61}[a-z0-9]$')


def normalize_bucket_name(raw_name: str) -> str:
    """Normalizes and validates a physical GCS bucket name.

    Strips leading 'gs://' prefix, surrounding whitespace, and trailing slashes.
    Raises ValueError on any invalid or empty format.
    """
    if raw_name is None:
        raise ValueError('Bucket name cannot be empty')
    cleaned = raw_name.strip()
    if not cleaned:
        raise ValueError('Bucket name cannot be empty')
    if cleaned.startswith('gs://'):
        cleaned = cleaned[5:]
    cleaned = cleaned.rstrip('/')

    if not _BUCKET_NAME_RE.fullmatch(cleaned):
        raise ValueError(f"Invalid GCS bucket name format: '{raw_name}'")
    if '..' in cleaned or '.-' in cleaned or '-.' in cleaned:
        raise ValueError(f"Invalid dot/dash sequence in bucket name: '{raw_name}'")
    return cleaned


def get_physical_media_bucket() -> str:
    """Returns the physical GCS bucket name for runtime read/write operations.

    If POPCORN_MEDIA_STORAGE_BUCKET is absent (unset in environment), falls back
    to LOGICAL_MEDIA_BUCKET for 100% backward compatibility. If
    POPCORN_MEDIA_STORAGE_BUCKET is explicitly defined (even as empty or
    whitespace), validates and normalizes the bucket name, raising ValueError on
    any empty or malformed value (no silent fallback to old bucket).
    """
    env_val = os.environ.get(STORAGE_ENV_VAR)
    if env_val is not None:
        return normalize_bucket_name(env_val)
    return LOGICAL_MEDIA_BUCKET


def is_valid_logical_bucket(bucket_name: str | None) -> bool:
    """Validates that an asset's recorded bucket matches the immutable logical bucket identity."""
    return bucket_name == LOGICAL_MEDIA_BUCKET
