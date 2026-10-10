"""카드 소개 문장 도구: 소개만 바꾸고 설명 수정 -> 심사 승인 -> 고객 공개 순서로 기존 함수를 부른다.
미리보기는 되돌리고, 실패하면 전부 되돌린다. 실제 DB/GCS 없이 확인한다."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from tools import apply_pc_card_intro as m
from api import pc_configuration_copy as copy_mod
from api import pc_configuration_edit as edit
from api import pc_configuration_review as review
from api import pc_customer_publication as publication

OPERATOR = dict(operator_id=4, name='운영자', role='operator', status='활성')
CONTENT = dict(title='할 일도 하고 게임도 즐기는 나만의 PC', intro='예전 소개 문장', benefits=[['빠름', '설명']],
               scene='장면', checks=[], faq=[], recommendation_policy={},
               _review=dict(state='approved', basis='a' * 64,
                            findings={'copy': dict(confirmed=True, evidence='설명과 구성이 일치함을 확인'),
                                      'price': dict(confirmed=True, evidence='가격 기준과 조립 포함 확인')}))
REQUIRED = {'copy': '변경 구성과 상품 설명 일치', 'price': '가격 기준·조립 서비스 포함 조건 확인'}


class Tx:
    def __init__(self, log): self.log = log
    def commit(self): self.log.append('commit')
    def rollback(self): self.log.append('rollback')


class Rows:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return self
    def first(self): return self.rows[0] if self.rows else None


class Conn:
    def __init__(self, log, operator): self.log, self.operator = log, operator
    def execution_options(self, **kw): self.log.append(kw['isolation_level']); return self
    def begin(self): return Tx(self.log)
    def close(self): self.log.append('close')
    def execute(self, clause, params=None):
        assert 'FROM admin_operators' in str(clause), str(clause)
        return Rows([self.operator] if self.operator else [])


class Engine:
    def __init__(self, operator=OPERATOR): self.log, self.operator = [], operator
    def connect(self): return Conn(self.log, self.operator)


def state(revision, basis, st='approved', blockers=()):
    return dict(revision=revision, basis=basis, state=st, eligible=st == 'approved', blockers=list(blockers),
                required=dict(REQUIRED))


class Fake:
    """load_review / read_current 를 단계에 맞춰 돌려주고, 쓰기 호출 순서를 적는다."""
    def __init__(self, allowed=True, review_state='approved', intro='예전 소개 문장', fail=None):
        self.calls, self.fail = [], fail
        self.config = dict(configuration_id='cfg-1', revision=7, content=dict(CONTENT, intro=intro))
        self.reviews = [state(7, 'a' * 64, review_state), state(8, 'b' * 64, 'stale')]
        self.pubs = [dict(allowed=allowed, state='approved' if allowed else 'stale', reason=None if allowed else 'x',
                          publication_basis='p' * 64, event_seq=3, revision=7, basis='a' * 64),
                     dict(allowed=False, state='stale', reason='publication_basis_changed', publication_basis='q' * 64,
                          event_seq=3, revision=9, basis='c' * 64),
                     dict(allowed=True, state='approved', reason=None, publication_basis='q' * 64,
                          event_seq=4, revision=9, basis='c' * 64)]

    def patches(self):
        return [patch.object(copy_mod, 'read_sold_offer_configuration', lambda c, code: dict(configuration_id='cfg-1')),
                patch.object(review, 'load_review', self.load_review),
                patch.object(review, 'save_review', self.save_review),
                patch.object(edit, 'save_copy', self.save_copy),
                patch.object(publication, 'read_current', self.read_current),
                patch.object(publication, 'approve', self.approve)]

    def load_review(self, c, identity, lock=False):
        return self.config, [], [], self.reviews.pop(0)

    def read_current(self, c, identity, source_reader=None):
        return self.pubs.pop(0)

    def save_copy(self, c, identity, body, actor):
        self.calls.append(('save_copy', body.revision, body.content.intro, body.source_basis, actor['operator_id']))

    def save_review(self, c, identity, body, actor):
        self.calls.append(('save_review', body.revision, body.basis, body.action,
                           {k: v.evidence for k, v in body.findings.items()}))

    def approve(self, c, identity, **kw):
        if self.fail == 'approve':
            raise HTTPException(409, 'publication_sequence_changed')
        self.calls.append(('approve', kw['expected_seq'], kw['revision'], kw['review_basis'], kw['publication_basis']))


def run(fake, engine=None, apply=False, intro='새 소개 문장'):
    engine = engine or Engine()
    ps = fake.patches()
    for p in ps: p.start()
    try:
        row = m.run_one(engine, 98149, intro, apply=apply, operator_id=4, source='docs/copy/x.json@sha256:abc',
                        reader_factory=lambda: object())
    finally:
        for p in ps: p.stop()
    return row, engine.log


class Cards(unittest.TestCase):
    def write(self, data):
        f = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(data, f, ensure_ascii=False); f.close()
        return f.name

    def test_reads_cards(self):
        cards, digest = m.load_cards(self.write({'cards': [{'product_code': 98149, 'intro': ' 새 문장 '}]}))
        self.assertEqual(cards, {98149: '새 문장'})
        self.assertEqual(len(digest), 64)

    def test_rejects_bad_files(self):
        for data in [{}, {'cards': []}, {'cards': [{'product_code': '98149', 'intro': 'x'}]},
                     {'cards': [{'product_code': 1, 'intro': ''}]},
                     {'cards': [{'product_code': 1, 'intro': 'x', 'title': 'y'}]},
                     {'cards': [{'product_code': 1, 'intro': 'x'}, {'product_code': 1, 'intro': 'y'}]}]:
            with self.assertRaises(ValueError, msg=data):
                m.load_cards(self.write(data))

    def test_cli_refuses_product_missing_from_file(self):
        path = self.write({'cards': [{'product_code': 98149, 'intro': '문장'}]})
        with self.assertRaises(SystemExit):
            m.main(['--file', path, '--product', '113455'], out=lambda *a: None)


class Edit(unittest.TestCase):
    def test_only_intro_changes(self):
        body = m.build_edit(dict(revision=7, content=CONTENT), '새 문장', 'a' * 64)
        self.assertEqual(body.content.intro, '새 문장')
        self.assertEqual(body.source_basis, 'a' * 64)

    def test_other_field_drift_is_refused(self):
        content = dict(CONTENT, scene='장면  ')   # 형식 검사가 공백을 지우면 scene 도 바뀐다
        with self.assertRaisesRegex(m.Refuse, 'scene'):
            m.build_edit(dict(revision=7, content=content), '새 문장', 'a' * 64)

    def test_legacy_shape_is_refused(self):
        content = dict(CONTENT, benefits=['옛 형식 한 줄'])
        with self.assertRaisesRegex(m.Refuse, '형식 검사'):
            m.build_edit(dict(revision=7, content=content), '새 문장', 'a' * 64)

    def test_findings_reuse_prior_and_note_copy(self):
        found = m.reuse_findings(CONTENT['_review'], REQUIRED, '카드 소개 문장만 교체')
        self.assertTrue(found['copy'].evidence.startswith('카드 소개 문장만 교체 / 이전 근거: 설명과'))
        self.assertEqual(found['price'].evidence, '가격 기준과 조립 포함 확인')

    def test_new_required_key_is_refused(self):
        with self.assertRaisesRegex(m.Refuse, '새 항목'):
            m.reuse_findings(CONTENT['_review'], dict(REQUIRED, extra='새 항목'), 'x')


class Flow(unittest.TestCase):
    def test_preview_runs_three_steps_in_order_then_rolls_back(self):
        fake = Fake()
        row, log = run(fake)
        self.assertEqual([c[0] for c in fake.calls], ['save_copy', 'save_review', 'approve'])
        self.assertEqual(fake.calls[0][1:], (7, '새 소개 문장', 'a' * 64, 4))
        self.assertEqual(fake.calls[1][1:4], (8, 'b' * 64, 'approve'))
        self.assertEqual(fake.calls[2][1:], (3, 9, 'c' * 64, 'q' * 64))
        self.assertEqual(log, ['REPEATABLE READ', 'rollback', 'close'])
        self.assertEqual((row['outcome'], row['committed'], row['publication_allowed']), ('changed', False, True))
        self.assertEqual((row['review_basis_before'], row['review_basis_after']), ('a' * 64, 'c' * 64))

    def test_apply_commits(self):
        row, log = run(Fake(), apply=True)
        self.assertEqual(log, ['REPEATABLE READ', 'commit', 'close'])
        self.assertTrue(row['committed'])

    def test_not_public_now_is_left_alone(self):
        fake = Fake(allowed=False)
        row, log = run(fake, apply=True)
        self.assertEqual((row['outcome'], fake.calls), ('refused', []))
        self.assertIn('고객 공개 상태가 아닙니다', row['reason'])
        self.assertNotIn('commit', log)

    def test_not_approved_now_is_left_alone(self):
        fake = Fake(review_state='stale')
        row, log = run(fake, apply=True)
        self.assertEqual((row['outcome'], fake.calls), ('refused', []))
        self.assertNotIn('commit', log)

    def test_publication_failure_rolls_everything_back(self):
        fake = Fake(fail='approve')
        row, log = run(fake, apply=True)
        self.assertEqual(row['outcome'], 'refused')
        self.assertIn('publication_sequence_changed', row['reason'])
        self.assertEqual([c[0] for c in fake.calls], ['save_copy', 'save_review'])
        self.assertEqual(log, ['REPEATABLE READ', 'rollback', 'close'])

    def test_same_sentence_writes_nothing(self):
        fake = Fake(intro='새 소개 문장')
        row, log = run(fake, apply=True)
        self.assertEqual((row['outcome'], fake.calls), ('unchanged', []))
        self.assertNotIn('commit', log)

    def test_inactive_operator_is_refused(self):
        fake = Fake()
        row, log = run(fake, engine=Engine(dict(OPERATOR, status='정지')), apply=True)
        self.assertEqual((row['outcome'], fake.calls), ('refused', []))
        self.assertNotIn('commit', log)

    def test_no_direct_writes_in_tool(self):
        source = Path(m.__file__).read_text(encoding='utf-8').upper()
        for word in ('UPDATE ', 'DELETE ', 'INSERT ', 'ADMIN_ENGINE_RULES', 'ADMIN_REPRICE'):
            self.assertNotIn(word, source)


if __name__ == '__main__':
    unittest.main()
