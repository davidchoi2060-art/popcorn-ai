"""Physical GCS transport for the unchanged logical media namespace.

Asset/approval JSON retains LOGICAL_BUCKET. Deployment configuration selects a
physical bucket; a missing object never falls back to another bucket. Replica
proofs are local, hash-pinned deployment artifacts, not request-supplied grants.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import quote

LOGICAL_BUCKET = 'popcorn-ai-product-media-045e861b'
SCHEMA = 'popcorn-media-replica-v1'
MAX_MANIFEST_BYTES = 32 * 1024 * 1024


class StorageConfigurationError(ValueError):
    pass


def storage_bucket(logical_bucket=LOGICAL_BUCKET):
    if logical_bucket != LOGICAL_BUCKET:
        raise StorageConfigurationError('unknown_logical_media_bucket')
    obsolete = os.environ.get('POPCORN_MEDIA_BUCKET', '').strip()
    if obsolete and obsolete != LOGICAL_BUCKET:
        raise StorageConfigurationError('logical_media_bucket_override_forbidden')
    value = os.environ.get('POPCORN_MEDIA_STORAGE_BUCKET', LOGICAL_BUCKET).strip()
    if (not 3 <= len(value) <= 222 or not re.fullmatch(r'[a-z0-9][a-z0-9_.-]*[a-z0-9]', value)
            or '..' in value or any(len(part) > 63 for part in value.split('.'))
            or re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', value)):
        raise StorageConfigurationError('invalid_physical_media_bucket')
    return value


def _key(key):
    if (type(key) is not str or not key or key.startswith('/') or '\\' in key
            or any(p in ('', '.', '..') for p in key.split('/'))
            or any(ord(c) < 32 or ord(c) == 127 for c in key)):
        raise StorageConfigurationError('invalid_media_object_key')
    return key


def object_url(logical_bucket, key):
    return 'https://storage.googleapis.com/storage/v1/b/%s/o/%s' % (
        quote(storage_bucket(logical_bucket), safe=''), quote(_key(key), safe=''))


def upload_url(logical_bucket=LOGICAL_BUCKET):
    return 'https://storage.googleapis.com/upload/storage/v1/b/%s/o' % quote(storage_bucket(logical_bucket), safe='')


def permissions_url(logical_bucket=LOGICAL_BUCKET):
    return 'https://storage.googleapis.com/storage/v1/b/%s/iam/testPermissions' % quote(storage_bucket(logical_bucket), safe='')


def inventory_objects(inventory):
    """Production inventory must name its actual bucket, not just matching keys."""
    physical = storage_bucket()
    if type(inventory) is not list:
        raise StorageConfigurationError('invalid_media_inventory')
    objects = {}
    for item in inventory:
        if (type(item) is not dict or type(item.get('name')) is not str
                or item['name'] in objects
                or (physical != LOGICAL_BUCKET and item.get('bucket') != physical)
                or (item.get('bucket') is not None and item['bucket'] != physical)):
            raise StorageConfigurationError('media_inventory_bucket_or_identity_mismatch')
        _key(item['name'])
        objects[item['name']] = item
    return objects


def _generation(value):
    return type(value) is str and re.fullmatch(r'[1-9][0-9]*', value) is not None


def _hash(value):
    return type(value) is str and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise StorageConfigurationError('duplicate_manifest_json_key')
        result[key] = value
    return result


@dataclass(frozen=True)
class ReplicaBinding:
    logical_bucket: str
    source_bucket: str
    destination_bucket: str
    key: str
    source_generation: str
    destination_generation: str
    sha256: str
    size: int
    content_type: str
    manifest_sha256: str


def replica_binding(logical_bucket, key, source_generation, sha256, size, content_type):
    """Return exact proof, or fail before any cloud access. Never select latest."""
    physical = storage_bucket(logical_bucket)
    _key(key)
    if (physical == logical_bucket or not _generation(source_generation) or not _hash(sha256)
            or type(size) is not int or size <= 0 or type(content_type) is not str or not content_type):
        raise StorageConfigurationError('invalid_replica_lookup')
    filename = os.environ.get('POPCORN_MEDIA_REPLICA_MANIFEST', '')
    pin = os.environ.get('POPCORN_MEDIA_REPLICA_MANIFEST_SHA256', '')
    path = Path(filename)
    if not filename or not path.is_absolute() or not _hash(pin):
        raise StorageConfigurationError('replica_manifest_unconfigured')
    try:
        with path.open('rb') as source:
            raw = source.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES or hashlib.sha256(raw).hexdigest() != pin:
            raise StorageConfigurationError('replica_manifest_hash_mismatch')
        data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object)
    except StorageConfigurationError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise StorageConfigurationError('replica_manifest_unreadable') from error
    if (type(data) is not dict or set(data) != {'schema', 'logical_bucket', 'source_bucket',
            'destination_bucket', 'verified_at', 'objects'} or data['schema'] != SCHEMA
            or data['logical_bucket'] != logical_bucket or data['source_bucket'] != LOGICAL_BUCKET
            or data['destination_bucket'] != physical or type(data['objects']) is not list):
        raise StorageConfigurationError('replica_manifest_contract_mismatch')
    try:
        timestamp = datetime.fromisoformat(data['verified_at'].replace('Z', '+00:00'))
        if timestamp.utcoffset() is None:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as error:
        raise StorageConfigurationError('replica_manifest_timestamp_invalid') from error
    found = None
    seen_source, seen_destination = set(), set()
    for item in data['objects']:
        if (type(item) is not dict or set(item) != {'key', 'source_generation', 'destination_generation',
                'sha256', 'size', 'content_type'} or not _generation(item.get('source_generation'))
                or not _generation(item.get('destination_generation')) or not _hash(item.get('sha256'))
                or type(item.get('size')) is not int or item['size'] <= 0
                or type(item.get('content_type')) is not str or not item['content_type']):
            raise StorageConfigurationError('replica_manifest_object_invalid')
        _key(item['key'])
        source_identity = (item['key'], item['source_generation'])
        destination_identity = (item['key'], item['destination_generation'])
        if source_identity in seen_source or destination_identity in seen_destination:
            raise StorageConfigurationError('replica_manifest_duplicate_binding')
        seen_source.add(source_identity)
        seen_destination.add(destination_identity)
        if source_identity == (key, source_generation):
            if (item['sha256'], item['size'], item['content_type']) != (sha256, size, content_type):
                raise StorageConfigurationError('replica_manifest_content_mismatch')
            found = ReplicaBinding(logical_bucket, data['source_bucket'], physical, key,
                source_generation, item['destination_generation'], sha256, size, content_type, pin)
    if found is None:
        raise StorageConfigurationError('replica_manifest_binding_missing')
    return found


def verify_binding(binding):
    if type(binding) is not ReplicaBinding:
        raise StorageConfigurationError('invalid_replica_binding')
    current = replica_binding(binding.logical_bucket, binding.key, binding.source_generation,
                              binding.sha256, binding.size, binding.content_type)
    if current != binding:
        raise StorageConfigurationError('replica_binding_changed')
    return binding
