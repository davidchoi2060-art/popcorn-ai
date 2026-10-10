"""Explicit server-only import CLI. Defaults to dry-run and denied authority.
No actor/permission/factory is accepted from CLI input. No generation or delete.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from api.pc_existing_media_import import Denied, Expected, Outcome


def validate_pins(pins):
    if not isinstance(pins, dict): raise Denied()
    files = {
        'runtime_sha256': 'api/pc_existing_media_import.py',
        'cli_sha256': 'tools/apply_existing_pc_media.py',
        'gpu_sha256': 'api/pc_media.py',
        'planner_sha256': 'tools/register_existing_pc_media.py',
        'schema_sha256': 'db/migrations/versions/0134_pc_media_import_provenance.py',
    }
    for field, path in files.items():
        if pins.get(field) != hashlib.sha256((ROOT / path).read_bytes()).hexdigest(): raise Denied()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if pins.get('integrated_baseline') != head: raise Denied()
    # HEAD alone does not cover uncommitted input changes; all five byte pins do.


def server_runtime():
    from api.pc_existing_media_import import ServerAuthority, Runtime, PgStore, GcsObjects
    authority = ServerAuthority()
    # Must fail before DB/credential setup until actual server verifiers are wired.
    authority.principal()
    from api.db import engine
    return Runtime(PgStore(engine, ROOT.parents[1] / 'outputs' / 'assembled-pc-images-20260929'),
                   GcsObjects(), authority)


def main(argv=None, *, runtime_factory=server_runtime, pin_validator=validate_pins,
         environment=None, output=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product-code', type=int, required=True, choices=(113835, 113836))
    parser.add_argument('--expected-pins', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--request-id')
    args = parser.parse_args(argv)
    environment = os.environ if environment is None else environment
    output = sys.stdout if output is None else output
    try:
        if args.apply and environment.get('POPCORN_EXISTING_MEDIA_IMPORT_APPLY') != '1':
            raise Denied()
        pins = json.loads(args.expected_pins.read_text(encoding='utf-8-sig'))
        pin_validator(pins)
        expected = Expected(**pins['expected'])
        runtime = runtime_factory()  # only trusted SERVER wiring, never a CLI import path
        result = (runtime.apply(args.product_code, expected, args.request_id) if args.apply
                  else runtime.dry_run(args.product_code, expected))
    except Denied:
        result = Outcome('denied')
    except Exception:
        result = Outcome('preflight_unavailable')
    print(json.dumps(asdict(result), ensure_ascii=False), file=output)
    return 0 if result.state in ('dry_run', 'registered') else 2


if __name__ == '__main__':
    raise SystemExit(main())
