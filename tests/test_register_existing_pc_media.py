"""Only new pure-planner fixtures; pinned local originals are test inputs.
Fixture permission is not operating reuse/publication approval.
"""
from dataclasses import fields, replace
from pathlib import Path
import copy
import os
import sys

import pytest
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.register_existing_pc_media import (
    CaseEvidence, Decision, ImportBinding, OriginalInput, Ports,
    Unavailable, InfrastructureFailure, plan_import,
)

ARCHIVE = Path('D:/WORK/PopcornAI') / 'outputs' / 'assembled-pc-images-20260929'

# Original archive bytes live only on the development PC (D:/WORK); same rule as
# tests/conftest.py: skip only when that root is absent on this machine.
if not os.path.isdir('D:/WORK'):
    pytest.skip('개발 PC 전용 자료 없음: D:/WORK/PopcornAI/outputs/assembled-pc-images-20260929', allow_module_level=True)
MANIFEST = (ARCHIVE / 'manifest.json').read_bytes()
ORIGINALS = {code: (ARCHIVE / 'originals' / f'P{code}.png').read_bytes()
             for code in (113835, 113836)}


class TrustedFixture:
    def __init__(self, code=113835):
        self.code = code
        self.input = OriginalInput(MANIFEST, ORIGINALS[code])
        self.binding = ImportBinding(code, f'P{code}', f'P{code}', 2 if code == 113835 else 3,
            'a' * 64, CaseEvidence(129552 if code == 113835 else 129551,
                'DAVEN N1 MESH', 'black' if code == 113835 else 'white',
                'closed_mesh_opaque', 'N1_MESH', 'fixture-server-case-evidence'))
        self.permission = Decision.UNKNOWN
        self.subjects = []
        self.error = None
        self.bind_reads = 0
        self.change_on_recheck = False

    def original(self, code):
        if self.error:
            raise self.error
        return self.input

    def current_binding(self, code):
        self.bind_reads += 1
        if self.change_on_recheck and self.bind_reads > 1:
            return replace(self.binding, revision=self.binding.revision + 1)
        return self.binding

    def verify_reuse(self, subject):
        self.subjects.append(subject)
        return self.permission

    def ports(self):
        return Ports(self, self)


class ImportPlannerTests(unittest.TestCase):
    def trusted(self, code=113835):
        fixture = TrustedFixture(code)
        fixture.permission = Decision.ALLOW
        return fixture

    def test_exact_two_originals_and_provenance(self):
        for code in (113835, 113836):
            with self.subTest(code=code):
                fixture = self.trusted(code)
                result = plan_import(code, fixture.ports())
                self.assertEqual(result.state, 'planned')
                original = result.plan.provenance
                self.assertEqual(original.original_revision, 1)
                self.assertEqual(result.plan.binding.revision, 2 if code == 113835 else 3)
                self.assertTrue(original.qa_notes)
                self.assertIsNone(original.generation_model)
                self.assertIsNone(original.generation_time)
                self.assertIsNone(original.generation_actor)
                self.assertIsNone(original.original_visual_basis)
                if code == 113836:
                    self.assertEqual(original.reused_from, 'P113838')
                    self.assertTrue(original.reuse_exception)
                    self.assertIn('500GB', original.facts_change_reference)
                self.assertNotIn('job_id', {f.name for f in fields(result.plan)})
                self.assertNotIn('selected', {f.name for f in fields(result.plan)})
                with self.assertRaises(Exception):
                    original.original_revision = 3

    def test_unwired_unknown_withdrawn_and_client_values(self):
        self.assertEqual(plan_import(113835).state, 'unavailable')
        self.assertEqual(plan_import(113835, {'allowed': True}).state, 'unavailable')
        self.assertEqual(plan_import(113835, Ports(None, None)).state, 'unavailable')
        for decision in (Decision.UNKNOWN, Decision.DENY, Decision.WITHDRAWN, True, {'allowed': True}):
            with self.subTest(decision=decision):
                fixture = self.trusted()
                fixture.permission = decision
                self.assertEqual(plan_import(113835, fixture.ports()).state, 'unavailable')

    def test_mapping_and_revision_fail_closed(self):
        for delta in ({'product_code': 113836}, {'offer_id': 'P113836'},
                      {'configuration_id': ''}, {'revision': True}, {'revision': 0},
                      {'current_visual_basis': 'invalid'}):
            with self.subTest(delta=delta):
                fixture = self.trusted()
                fixture.binding = replace(fixture.binding, **delta)
                self.assertEqual(plan_import(113835, fixture.ports()).state, 'unavailable')
                self.assertEqual(fixture.subjects, [])

    def test_actual_configuration_not_inferred_from_sku(self):
        fixture = self.trusted()
        fixture.binding = replace(fixture.binding, configuration_id='registered-actual-config')
        self.assertEqual(plan_import(113835, fixture.ports()).plan.binding.configuration_id,
                         'registered-actual-config')

    def test_case_mismatch_or_unknown(self):
        for delta in ({'product_code': 129551}, {'model': 'another model'}, {'color': 'white'},
                      {'side_panel': 'glass'}, {'front': 'unknown'}, {'source_reference': ''}):
            with self.subTest(delta=delta):
                fixture = self.trusted()
                fixture.binding = replace(fixture.binding, case=replace(fixture.binding.case, **delta))
                self.assertEqual(plan_import(113835, fixture.ports()).state, 'unavailable')

    def test_original_and_manifest_tampering(self):
        for which in ('manifest_bytes', 'original_bytes', 'other_sku'):
            with self.subTest(which=which):
                fixture = self.trusted()
                delta = {'original_bytes': ORIGINALS[113836]} if which == 'other_sku' else {
                    which: getattr(fixture.input, which) + b'altered'}
                fixture.input = replace(fixture.input, **delta)
                self.assertEqual(plan_import(113835, fixture.ports()).state, 'unavailable')

    def test_internal_basis_change_does_not_require_provider(self):
        fixture = self.trusted(113836)
        fixture.binding = replace(fixture.binding, revision=4, current_visual_basis='b' * 64)
        before = copy.deepcopy(fixture.input)
        result = plan_import(113836, fixture.ports())
        self.assertEqual(result.state, 'planned')
        self.assertEqual(result.plan.binding.current_visual_basis, 'b' * 64)
        self.assertIsNone(result.plan.provenance.original_visual_basis)
        self.assertEqual(fixture.input, before)
        # Sources offer only two read methods; no write/provider capability is given.
        self.assertFalse(any(hasattr(fixture, name) for name in
                             ('generate', 'upload', 'select', 'publish', 'execute', 'commit')))

    def test_changed_binding_on_recheck(self):
        fixture = self.trusted()
        fixture.change_on_recheck = True
        self.assertEqual(plan_import(113835, fixture.ports()).state, 'unavailable')

    def test_error_classification_without_details(self):
        for error, state in ((Unavailable('private'), 'unavailable'),
                             (InfrastructureFailure('private'), 'temporarily_unavailable')):
            fixture = self.trusted()
            fixture.error = error
            result = plan_import(113835, fixture.ports())
            self.assertEqual(result.state, state)
            self.assertNotIn('private', repr(result))

    def test_descriptor_initialization_error_is_protected(self):
        class Broken:
            def original(self, code):
                return None
            @property
            def current_binding(self):
                raise InfrastructureFailure('private adapter')
        self.assertEqual(plan_import(113835, Ports(Broken(), self.trusted())).state,
                         'temporarily_unavailable')

    def test_permission_withdrawn_on_recheck(self):
        fixture = self.trusted()
        def permission(subject):
            fixture.subjects.append(subject)
            return Decision.ALLOW if len(fixture.subjects) == 1 else Decision.WITHDRAWN
        fixture.verify_reuse = permission
        self.assertEqual(plan_import(113835, fixture.ports()).state, 'unavailable')

    def test_other_products_and_non_integer_identity_denied(self):
        for code in (113838, True, '113835', 0):
            self.assertEqual(plan_import(code, self.trusted().ports()).state, 'unavailable')


if __name__ == '__main__':
    unittest.main()
