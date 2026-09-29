"""Read-only presentation of prior research; never an approval input."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def snapshots():
    return json.loads((Path(__file__).parent / 'data/pc_catalog_review_snapshot.json').read_text(encoding='utf-8'))['records']


def review_snapshot(identity, parts):
    record = snapshots().get(identity)
    if record is None:
        return None
    current = sorted((p['slot'], str(p['source_code']), int(p['quantity']))
                     for p in parts if not p['pseudo'])
    previous = sorted((slot, code, int(qty)) for slot, code, qty in record['parts'])
    return {k: v for k, v in record.items() if k != 'parts'} | {
        'bom_matches': current == previous,
        'approval_basis': False,
    }
