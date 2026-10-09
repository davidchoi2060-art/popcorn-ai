"""New CLI fixtures; trusted factory injection only, never operating apply."""
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.pc_existing_media_import import Expected, Outcome, Denied
from tools.apply_existing_pc_media import main, validate_pins


class FakeRuntime:
    def __init__(self): self.calls = []
    def dry_run(self, code, expected):
        self.calls.append(('dry_run', code))
        return Outcome('dry_run')
    def apply(self, code, expected, request):
        self.calls.append(('apply', code, request))
        return Outcome('registered', request, 'fixture-job')


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='media-cli-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.pins = Path(self.temp.name) / 'pins.json'
        expected = Expected(2, 'a' * 64, 'b' * 64, 'c' * 64, 'd' * 64)
        self.pins.write_text(json.dumps({'expected': asdict(expected)}), encoding='utf-8')
        self.args = ['--product-code', '113835', '--expected-pins', str(self.pins)]
        self.output = io.StringIO()
        self.runtime = FakeRuntime()

    def run_cli(self, extra=(), environment=None, **kwargs):
        return main(self.args + list(extra), runtime_factory=lambda: self.runtime,
                    pin_validator=lambda pins: None, environment=environment or {},
                    output=self.output, **kwargs)

    def test_default_dry_run_no_apply(self):
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(self.runtime.calls, [('dry_run', 113835)])

    def test_apply_requires_explicit_environment_even_with_flag(self):
        self.assertEqual(self.run_cli(['--apply']), 2)
        self.assertEqual(self.runtime.calls, [])
        self.assertEqual(json.loads(self.output.getvalue())['state'], 'denied')

    def test_apply_explicit_server_fixture_only(self):
        self.assertEqual(self.run_cli(['--apply', '--request-id', 'stable-request'],
            {'POPCORN_EXISTING_MEDIA_IMPORT_APPLY': '1'}), 0)
        self.assertEqual(self.runtime.calls, [('apply', 113835, 'stable-request')])

    def test_default_real_factory_remains_denied_without_authority(self):
        # Real default factory fails before importing api.db/creating credentials.
        with patch.dict(sys.modules, {'api.db': None}):
            status = main(self.args + ['--apply'], pin_validator=lambda pins: None,
                environment={'POPCORN_EXISTING_MEDIA_IMPORT_APPLY': '1'}, output=self.output)
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(self.output.getvalue())['state'], 'denied')

    def test_bad_pins_rejected_before_factory(self):
        with self.assertRaises(Denied): validate_pins({'runtime_sha256': 'wrong'})
        def denied(pins): raise Denied()
        status = main(self.args, runtime_factory=lambda: self.fail('factory must not run'),
                      pin_validator=denied, environment={}, output=self.output)
        self.assertEqual(status, 2)

    def test_cli_actor_and_authority_cannot_be_injected(self):
        with patch('sys.stderr', io.StringIO()):
            for option in ('--actor', '--authority', '--factory', '--delete'):
                with self.subTest(option=option), self.assertRaises(SystemExit):
                    self.run_cli([option, 'client-supplied'])
        self.assertFalse(self.runtime.calls)

    def test_preflight_exception_no_secret_details(self):
        status = main(self.args, runtime_factory=lambda: (_ for _ in ()).throw(RuntimeError('secret DSN')),
                      pin_validator=lambda pins: None, environment={}, output=self.output)
        self.assertEqual(status, 2)
        self.assertNotIn('secret', self.output.getvalue())


if __name__ == '__main__': unittest.main()
