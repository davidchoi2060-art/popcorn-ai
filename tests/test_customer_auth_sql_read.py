"""New Q1 injected-executor fixtures only; no completed suites or DB imports."""
import ast
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import socket
import subprocess
import sys
import unittest


def deny_live_io(event, args):
    if event in ("socket.connect", "socket.connect_ex", "socket.getaddrinfo", "subprocess.Popen", "os.system"):
        raise AssertionError("Q1 live IO forbidden")
    if event == "import" and args:
        name = args[0]
        if name in ("api.db", "api.main", "api.auth") or name.split(".")[0] in ("psycopg", "psycopg2", "pg8000", "sqlalchemy"):
            raise AssertionError("Q1 live DB import forbidden")
    if event == "open" and args and isinstance(args[0], (str, bytes)):
        if str(args[0]).replace("\\", "/").lower().endswith("/.env"):
            raise AssertionError("Q1 secrets forbidden")


sys.addaudithook(deny_live_io)
from api import customer_auth_sql_read as q

DIGEST = "a" * 64
CONTEXT = "11111111-1111-4111-8111-111111111111"
SUBJECT = "22222222-2222-4222-8222-222222222222"
PROOF = "33333333-3333-4333-8333-333333333333"


def session_row(**changes):
    row = dict(credential_hash=DIGEST, member_id=101, verified_identity_id=17,
        auth_context_id=CONTEXT, issued_auth_revision=1, issued_at_epoch=100,
        expires_at_epoch=200, revoked_at_epoch=None, proof_ref=PROOF,
        canonical_member_id=101, auth_subject=SUBJECT, auth_revision=1,
        status="active", nickname="회원", email=None, identity_id=17,
        identity_member_id=101, issuer_key="fixture-app", issuer="https://issuer.example.invalid",
        subject="Opaque Case-Sensitive Subject", mapping_verified_at_epoch=90,
        verification_method="fixture-verified", registration_ref="fixture-registration",
        identity_revoked_at_epoch=None, receipt_ref=PROOF, receipt_digest=DIGEST,
        receipt_member_id=101, receipt_identity_id=17, receipt_context_id=CONTEXT,
        receipt_revision=1, receipt_issued_at=100, receipt_expires_at=200,
        receipt_issuer_key="fixture-app", receipt_issuer="https://issuer.example.invalid",
        receipt_subject="Opaque Case-Sensitive Subject", principal_verified_at_epoch=100,
        receipt_verification_method="fixture-verified", receipt_registration_ref="fixture-registration",
        authority_ref="fixture-authority-only", exact_subject_count=1,
        observed_epoch_exact=Decimal("120.999999"), isolation_level="read committed", read_only="on")
    row.update(changes)
    return row


def member_row(**changes):
    row = {k: session_row()[k] for k in ("member_id", "auth_subject", "auth_revision", "status", "nickname", "email",
        "observed_epoch_exact", "isolation_level", "read_only")}
    row.update(changes)
    return row


class FixtureExecutor:
    def __init__(self, rows=None):
        self.rows = (session_row(),) if rows is None else rows
        self.sequence = 0
        self.calls = []
        self.enabled = True
        self.error = None
        self.after = None
        self.stamp_changes = {}

    def ready(self, requirements):
        return self.enabled

    def observe(self, query, parameters, *, requirements):
        self.calls.append((query, parameters, requirements))
        if self.error:
            raise self.error
        self.sequence += 1
        result = q.StatementObservation(self.sequence, q.SCHEMA_CONTRACT,
            "read committed", True, True, True, self.rows)
        if self.after:
            self.after()
        return replace(result, **self.stamp_changes)


class Q1Fixtures(unittest.TestCase):
    def failed(self, executor, *, digest=DIGEST):
        with self.assertRaises(q.SQLReadUnavailable) as caught:
            q.SQLReadPort(executor).read_current_session(digest)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(dict(caught.exception.detail), {"code": "auth_unavailable"})
        self.assertEqual(caught.exception.headers["Cache-Control"], "no-store")
        self.assertEqual(str(caught.exception), "auth_unavailable")

    def test_original_proof_time_is_separate_and_clock_is_exact(self):
        result = q.SQLReadPort(FixtureExecutor()).read_current_session(DIGEST)
        self.assertEqual((result.identities[0].verified_at, result.provenance.verified_at,
            result.session.issued_at, result.now), (90, 100, 100, 120))
        self.assertEqual(result.observed_epoch_exact, Decimal("120.999999"))
        self.assertEqual(result.issuance_binding, q.IssuanceBinding(PROOF,DIGEST,101,17,CONTEXT,1,100,200))
        self.assertNotIn(DIGEST, repr(result))

    def test_unknown_digest_only_is_none(self):
        executor = FixtureExecutor(())
        self.assertIsNone(q.SQLReadPort(executor).read_current_session(DIGEST))
        self.assertEqual(dict(executor.calls[0][1]), {"credential_hash": DIGEST})

    def test_present_digest_missing_joins_is_not_unknown(self):
        for key in ("canonical_member_id", "auth_subject", "identity_id", "receipt_ref", "authority_ref"):
            with self.subTest(key=key):
                self.failed(FixtureExecutor((session_row(**{key: None}),)))

    def test_missing_column_is_structural_unavailable(self):
        row = session_row(); del row["receipt_member_id"]
        self.failed(FixtureExecutor((row,)))

    def test_duplicate_digest_rows_are_not_first_row_success(self):
        self.failed(FixtureExecutor((session_row(), session_row())))

    def test_subject_cardinality_requires_exact_one_integer(self):
        for count in (0, 2, True, Decimal(1), None):
            with self.subTest(count=count):
                self.failed(FixtureExecutor((session_row(exact_subject_count=count),)))

    def test_all_eight_receipt_binding_fields_reject_replay(self):
        bad = dict(receipt_ref=SUBJECT, receipt_digest="b"*64, receipt_member_id=102,
            receipt_identity_id=18, receipt_context_id=SUBJECT, receipt_revision=2,
            receipt_issued_at=99, receipt_expires_at=201)
        for key, value in bad.items():
            with self.subTest(key=key):
                self.failed(FixtureExecutor((session_row(**{key:value}),)))

    def test_cross_member_and_identity_join_defects(self):
        for key in ("canonical_member_id", "identity_member_id", "identity_id"):
            with self.subTest(key=key):
                self.failed(FixtureExecutor((session_row(**{key:999}),)))

    def test_registration_and_subject_are_exact_opaque_values(self):
        for key in ("receipt_subject", "receipt_issuer_key", "receipt_issuer", "receipt_verification_method", "receipt_registration_ref"):
            with self.subTest(key=key):
                self.failed(FixtureExecutor((session_row(**{key:"wrong"}),)))
        row = session_row(subject=" With Spaces ",receipt_subject=" With Spaces ")
        self.assertEqual(q.SQLReadPort(FixtureExecutor((row,))).read_current_session(DIGEST).provenance.subject," With Spaces ")

    def test_non_integer_event_values_are_never_floored(self):
        for value in (Decimal("100.1"), 100.1, True, "100", datetime(1970,1,1,tzinfo=timezone.utc)):
            for key in ("issued_at_epoch", "principal_verified_at_epoch", "mapping_verified_at_epoch", "expires_at_epoch", "revoked_at_epoch"):
                with self.subTest(key=key,value=value):
                    self.failed(FixtureExecutor((session_row(**{key:value}),)))

    def test_flooring_cannot_hide_reversed_issuance_chronology(self):
        self.failed(FixtureExecutor((session_row(principal_verified_at_epoch=101),)))
        self.failed(FixtureExecutor((session_row(expires_at_epoch=100,receipt_expires_at=100),)))
        self.failed(FixtureExecutor((session_row(issued_at_epoch=Decimal("100.1"),
            receipt_issued_at=Decimal("100.1"),principal_verified_at_epoch=Decimal("100.9")),)))

    def test_exact_clock_type_and_range(self):
        for value in (120,120.5,"120",Decimal("NaN"),Decimal("Infinity"),Decimal("-0.1"),Decimal(q.MAX_BIGINT)+1):
            with self.subTest(value=value):
                self.failed(FixtureExecutor((session_row(observed_epoch_exact=value),)))

    def test_current_clock_bucket_preserves_integer_event_comparisons(self):
        for value in (Decimal("199.999999"),Decimal("200"),Decimal("200.000001")):
            result=q.SQLReadPort(FixtureExecutor((session_row(observed_epoch_exact=value),))).read_current_session(DIGEST)
            self.assertEqual(result.session.expires_at<=value, result.session.expires_at<=result.now)
            self.assertEqual(result.session.issued_at>value, result.session.issued_at>result.now)

    def test_state_denials_are_preserved_for_existing_c1_c4(self):
        row=session_row(revoked_at_epoch=119,identity_revoked_at_epoch=118,status="blocked",auth_revision=2,
            observed_epoch_exact=Decimal("250.1"))
        result=q.SQLReadPort(FixtureExecutor((row,))).read_current_session(DIGEST)
        self.assertEqual((result.session.revoked_at,result.identities[0].revoked_at,result.member.status,
            result.member.auth_revision,result.session.issued_auth_revision),(119,118,"blocked",2,1))

    def test_each_read_observes_new_rows_and_clock_in_fixture(self):
        executor=FixtureExecutor(); port=q.SQLReadPort(executor)
        before=port.read_current_session(DIGEST)
        executor.rows=(session_row(revoked_at_epoch=121,auth_revision=2,
            observed_epoch_exact=Decimal("122.3")),)
        after=port.read_current_session(DIGEST)
        self.assertEqual(len(executor.calls),2)
        self.assertIsNone(before.session.revoked_at)
        self.assertEqual(after.session.revoked_at,121)
        self.assertEqual(after.member.auth_revision,2)
        self.assertEqual(after.observed_epoch_exact,Decimal("122.3"))

    def test_reused_observation_sequence_is_rejected(self):
        executor=FixtureExecutor(); port=q.SQLReadPort(executor)
        port.read_current_session(DIGEST); executor.stamp_changes={"sequence":1}
        with self.assertRaises(q.SQLReadUnavailable): port.read_current_session(DIGEST)

    def test_invalid_executor_metadata_even_on_unknown_digest(self):
        for fields in ({"primary":False},{"read_only":1},{"isolation":"repeatable read"},
            {"schema_contract":"other"},{"transaction_closed":False},{"sequence":True},{"rows":[]}):
            with self.subTest(fields=fields):
                executor=FixtureExecutor(()); executor.stamp_changes=fields; self.failed(executor)

    def test_sql_row_clock_metadata_matches_read_requirements(self):
        for fields in ({"read_only":"off"},{"isolation_level":"repeatable read"}):
            with self.subTest(fields=fields): self.failed(FixtureExecutor((session_row(**fields),)))

    def test_not_ready_or_ready_lost_before_return(self):
        for enabled in (False,1):
            executor=FixtureExecutor(); executor.enabled=enabled; self.failed(executor)
            self.assertEqual(executor.calls,[])
        executor=FixtureExecutor(); executor.after=lambda:setattr(executor,"enabled",False)
        self.failed(executor)

    def test_executor_failure_does_not_leak_private_error(self):
        executor=FixtureExecutor(); executor.error=RuntimeError("private " + DIGEST)
        self.failed(executor)

    def test_bad_lookup_input_never_reaches_executor(self):
        for value in (None,True,DIGEST.upper(),"short",101):
            with self.subTest(value=value):
                executor=FixtureExecutor(); self.failed(executor,digest=value); self.assertEqual(executor.calls,[])

    def test_member_read_requires_exact_canonical_id_and_auth_fields(self):
        executor=FixtureExecutor((member_row(),)); port=q.SQLReadPort(executor)
        self.assertEqual(port.read_current_member(101).member_id,101)
        self.assertEqual(dict(executor.calls[0][1]),{"member_id":101})
        for fields in ({"member_id":102},{"auth_subject":None},{"auth_revision":0},{"member_id":True}):
            executor=FixtureExecutor((member_row(**fields),))
            with self.subTest(fields=fields),self.assertRaises(q.SQLReadUnavailable):
                q.SQLReadPort(executor).read_current_member(101)

    def test_member_none_duplicate_and_invalid_input(self):
        self.assertIsNone(q.SQLReadPort(FixtureExecutor(())).read_current_member(101))
        for executor,value in ((FixtureExecutor((member_row(),member_row())),101),
            (FixtureExecutor(),True),(FixtureExecutor(),0),(FixtureExecutor(),"101")):
            with self.subTest(value=value),self.assertRaises(q.SQLReadUnavailable):
                q.SQLReadPort(executor).read_current_member(value)

    def test_detached_frozen_result_and_readonly_parameters(self):
        row=session_row();executor=FixtureExecutor((row,));result=q.SQLReadPort(executor).read_current_session(DIGEST)
        row["nickname"]="changed";row["receipt_subject"]="changed"
        self.assertEqual(result.member.nickname,"회원")
        with self.assertRaises(FrozenInstanceError):result.now=999
        with self.assertRaises(TypeError):executor.calls[0][1]["member_id"]=102

    def test_bigint_and_null_event_boundaries(self):
        for fields in ({"member_id":q.MAX_BIGINT+1},{"issued_auth_revision":True},
            {"revoked_at_epoch":-1},{"principal_verified_at_epoch":None},{"receipt_digest":None}):
            with self.subTest(fields=fields):self.failed(FixtureExecutor((session_row(**fields),)))

    def test_query_does_not_hide_missing_join_or_current_state(self):
        query=q.SESSION_QUERY.lower()
        self.assertIn("left join public.members",query)
        self.assertIn("left join public.member_session_issuance_receipts",query)
        self.assertIn("count(*)",query)
        self.assertNotIn("limit",query)
        self.assertEqual(query.split("where s.credential_hash=",1)[1],":credential_hash")
        self.assertNotIn("now()",query)
        self.assertNotIn("clock_timestamp",query)
        for verb in ("update ","insert ","delete ","commit", "last_seen"):
            self.assertNotIn(verb,query)

    def test_module_has_no_database_runtime_or_authority_import(self):
        tree=ast.parse(Path(q.__file__).read_text(encoding="utf-8"))
        imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertNotIn("api.db",imports)
        self.assertNotIn("sqlalchemy",imports)
        self.assertFalse(hasattr(q,"RUNTIME_READ_PORT"))
        self.assertFalse(hasattr(q,"restore_verified_principal"))

    def test_live_io_guard_is_active(self):
        with self.assertRaisesRegex(AssertionError,"Q1 live IO"):
            socket.getaddrinfo("example.invalid",443)
        with self.assertRaisesRegex(AssertionError,"Q1 live IO"):
            subprocess.Popen(["must-not-run"])


if __name__ == "__main__":
    unittest.main()
