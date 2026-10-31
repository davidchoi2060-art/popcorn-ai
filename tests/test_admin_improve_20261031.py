"""관리자단 개선 PR-1 (2026-10-31) — 구매 상담 신청 거르기 · AI 슈퍼컴퓨터 보관 표시. DB 서버 없이 확인하는 것.

고객 화면이 10월에 늘린 문의 주제(0165 AI 슈퍼컴퓨터 · 0174 기업 컨설팅 · /mvp4 AI 패키지)를 관리자 처리함이
가를 수 있는지, AI 장비 「견적에 저장」(#373)이 「쇼핑몰 완제품」으로 잘못 보이던 것이 고쳐졌는지,
선택지가 서버 상수에서만 오는지 본다. 문의 종류 판정은 SQL 한 곳(KIND_CASE)이라 경계 행을 SQLite 메모리 표에
넣어 **행 단위로 실행**해 대조한다 — 문자열 모양만 보는 검사가 아니다. 실제 조회는 개발 DB(읽기 전용)로 따로 확인했다(PR 본문).
"""
import pathlib
import sqlite3
import unittest

from fastapi import HTTPException

from api import admin_mvp3_links as L
from api import admin_page_intro
from api import admin_purchase_inquiries as AP
from api import customer_surface as cs
from api import mvp3_purchase_inquiry as PI

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXED = '{"product_code": 129615, "intent": "quote", "quantity": 1}'

# (주제, 본문, fixed_product, 기대 종류) — SQL 판정의 경계 행. 주제 값은 고객 접수 모듈의 상수를 쓴다.
ROWS = [
    ('AI 슈퍼컴퓨터 견적', None, FIXED, 'fixed'),
    ('기타', '[AI 패키지 견적 문의] 기본형', FIXED, 'fixed'),                       # fixed_product 가 있으면 머리글보다 앞선다
    (PI.SERVICE_TOPICS[0], None, None, 'service'),
    (PI.SERVICE_TOPICS[0], '[AI 패키지 견적 문의]', None, 'service'),                # 주제가 곧 종류 — 본문은 보지 않는다
    ('기타', '[기업 AI 업무개선 컨설팅] 30인 이하 기업 대상\n진입: 직접 방문', None, 'service'),   # 0174 이전 신청
    ('기타', '[AI 패키지 견적 문의] 기본형\n관심 기능: 회의록', None, 'ai_package'),
    ('기타', '[AI 패키지 도입 상담] 업무형', None, 'ai_package'),
    ('기타', ' [AI 패키지 견적 문의]', None, 'general'),                           # 머리글은 맨 앞이어야 한다
    ('기타', '문의: [AI 패키지 견적 문의]', None, 'general'),
    ('기타', '[ai 패키지 견적 문의]', None, 'general'),                           # 대소문자 — LIKE 는 글자 그대로
    ('기타', None, None, 'general'),
    ('기타', '', None, 'general'),
    ('기타', '그냥 궁금해서요', None, 'general'),
    ('여러 대 구매', '[AI 패키지 견적 문의]', None, 'general'),                    # 주제가 다르면 머리글만으로 가르지 않는다
    ('할인', None, None, 'general'),
]


def sqlite_rows():
    """경계 행을 넣은 SQLite 메모리 표 — PostgreSQL 과 같은 글자 그대로 LIKE 로 맞춘다."""
    con = sqlite3.connect(':memory:')
    con.execute('PRAGMA case_sensitive_like = ON')
    con.execute('CREATE TABLE purchase_inquiries (id INTEGER PRIMARY KEY, topic TEXT NOT NULL, message TEXT, fixed_product TEXT)')
    con.executemany('INSERT INTO purchase_inquiries (topic, message, fixed_product) VALUES (?, ?, ?)',
                    [(t, m, f) for t, m, f, _ in ROWS])
    return con


class SavedQuoteKind(unittest.TestCase):
    def test_ai_device_snapshot_is_not_a_mall_pc(self):
        snap = {'kind': 'ai_device', 'name': 'HP ZGX nano G1n', 'price': 5000000, 'product_code': 130449}
        self.assertEqual(L.kind(snap), ('ai_device', 'AI 슈퍼컴퓨터 장비'))
        self.assertEqual(L.kind({'kind': 'pc', 'name': 'x'})[0], 'mall')          # 일반 PC 보관은 그대로
        self.assertEqual(L.kind({'name': 'x'})[0], 'mall')                        # kind 를 안 적던 옛 보관도 그대로

    def test_precedence_unchanged(self):
        snap = {'kind': 'ai_device'}
        self.assertEqual(L.kind(snap, None, None, {'product_code': 1})[0], 'fixed_product')
        self.assertEqual(L.kind(snap, None, {'parts': []})[0], 'free_build')
        self.assertEqual(L.kind({'kind': 'ai_device', 'ai_composed': True})[0], 'ai_device')

    def test_consults_timeline_reads_the_same_rule(self):
        src = (ROOT / 'api/admin_mvp3_consults.py').read_text(encoding='utf-8')
        self.assertIn('L.kind(p)[1]', src)


class KindJudgedInSqlOnce(unittest.TestCase):
    """판정식은 SQL 한 곳 — 행 표시(KIND_CASE) · 거르기(KINDS) · 건수(KIND_COUNT_SQL)가 같은 행에 같은 답을 내는지 실행해 본다."""
    def test_case_gives_expected_kind_per_row(self):
        con = sqlite_rows()
        got = con.execute(f'SELECT id, {AP.KIND_CASE} FROM purchase_inquiries i ORDER BY id').fetchall()
        self.assertEqual([k for _, k in got], [exp for *_, exp in ROWS])

    def test_filters_partition_every_row_exactly_once_and_agree_with_case(self):
        con = sqlite_rows()
        for key, pred in AP.KINDS.items():
            ids = {i for (i,) in con.execute(f'SELECT id FROM purchase_inquiries i WHERE {pred}')}
            expected = {i + 1 for i, (*_, exp) in enumerate(ROWS) if exp == key}
            self.assertEqual(ids, expected, key)
        ones = con.execute('SELECT ' + ' + '.join(f'({p})' for p in AP.KINDS.values()) + ' FROM purchase_inquiries i').fetchall()
        self.assertEqual({n for (n,) in ones}, {1})

    def test_count_sql_matches_rows(self):
        con = sqlite_rows()
        con.row_factory = sqlite3.Row
        row = con.execute(AP.KIND_COUNT_SQL.replace('{where}', 'TRUE')).fetchone()
        counts = {k: row[k] for k, _ in AP.INQUIRY_KINDS}
        self.assertEqual(counts, {k: sum(1 for *_, exp in ROWS if exp == k) for k, _ in AP.INQUIRY_KINDS})
        self.assertEqual(sum(counts.values()), len(ROWS))
        self.assertIn('{where}', AP.KIND_COUNT_SQL)                               # list_inquiries 가 범위를 넣는 자리

    def test_select_carries_the_same_case_to_rows(self):
        self.assertIn(AP.KIND_CASE + ' AS inquiry_kind', AP._SELECT)
        src = (ROOT / 'api/admin_purchase_inquiries.py').read_text(encoding='utf-8')
        self.assertIn('r.get("inquiry_kind")', src)
        self.assertIn('kind_sql = KIND_COUNT_SQL.replace("{where}", test_w)', src)
        self.assertNotIn('def inquiry_kind(', src)                                 # 파이썬 쪽 판정식은 없다


class LabelOnlyInPython(unittest.TestCase):
    def test_suffix_only_when_purge_actually_emptied_other_topic(self):
        self.assertEqual(AP.inquiry_kind_label('general', '기타', None, purged=True), '일반 상담' + AP.PURGED_SUFFIX)
        self.assertEqual(AP.inquiry_kind_label('general', '기타', None, purged=False), '일반 상담')   # 기한만 지난 행은 아니다
        self.assertEqual(AP.inquiry_kind_label('general', '기타', '본문 있음', purged=True), '일반 상담')
        self.assertEqual(AP.inquiry_kind_label('general', '여러 대 구매', None, purged=True), '일반 상담')
        self.assertEqual(AP.inquiry_kind_label('service', '기타', None, purged=True), '기업 AI 업무개선 컨설팅')
        self.assertEqual(AP.inquiry_kind_label('ai_package'), 'AI 패키지 문의')
        self.assertEqual(AP.inquiry_kind_label('nope'), '일반 상담')

    def test_row_passes_actual_purge_not_deadline(self):
        src = (ROOT / 'api/admin_purchase_inquiries.py').read_text(encoding='utf-8')
        self.assertIn('purged=bool(r.get("contact_purged_at"))', src)
        self.assertNotIn('purged=gone', src)
        for word in ('파기 작업이 본문을 비운', AP.SERVICE_HEAD, '다른 조건과 무관'):
            self.assertIn(word, AP.KIND_NOTE)

    def test_labels_come_from_one_table(self):
        self.assertEqual(dict(AP.INQUIRY_KINDS), AP.KIND_LABEL)
        self.assertEqual(set(AP.KINDS), {k for k, _ in AP.INQUIRY_KINDS})


class Choices(unittest.TestCase):
    def test_topics_are_the_customer_modules_constants(self):
        self.assertEqual(AP.TOPIC_CHOICES, tuple(PI.TOPICS) + tuple(PI.FIXED_TOPICS.values()) + tuple(PI.SERVICE_TOPICS))
        self.assertEqual(len(AP.TOPIC_CHOICES), len(set(AP.TOPIC_CHOICES)))
        self.assertIn(AP.AI_PACKAGE_TOPIC, PI.TOPICS)
        src = (ROOT / 'db/migrations/versions/0174_purchase_inquiry_company_consulting.py').read_text(encoding='utf-8')
        for t in AP.TOPIC_CHOICES:                                                  # 선택지 전부가 DB CHECK 가 허용하는 주제다
            self.assertTrue(any(t in (ROOT / p).read_text(encoding='utf-8') for p in (
                'db/migrations/versions/0139_purchase_inquiries.py', 'db/migrations/versions/0165_purchase_inquiry_fixed_product.py',
                'db/migrations/versions/0174_purchase_inquiry_company_consulting.py')), t)
        self.assertIn(PI.SERVICE_TOPICS[0], src)

    def test_surfaces_follow_customer_surface(self):
        f = AP.filter_choices()
        self.assertEqual([s['key'] for s in f['surfaces']], list(cs.SURFACES) + [AP.SURFACE_UNKNOWN])
        self.assertEqual(f['surfaces'][-1]['label'], cs.label(None))
        self.assertEqual([k['key'] for k in f['kinds']], [k for k, _ in AP.INQUIRY_KINDS])
        self.assertEqual(f['topics'], list(AP.TOPIC_CHOICES))

    def test_unknown_values_are_400_before_db(self):
        for kw in ({'kind': 'nope'}, {'topic': '없는 주제'}, {'surface': 'mvp9'}):
            with self.assertRaises(HTTPException) as cm:
                AP.list_inquiries(**kw)
            self.assertEqual(cm.exception.status_code, 400, kw)


class CustomerScreenContract(unittest.TestCase):
    """머리글·주제는 /mvp4 화면이 보내는 값이다 — 화면이 바뀌면 이 판정도 같이 바뀌어야 한다."""
    def test_service_adapters_send_the_topic_and_heads_we_read(self):
        src = (ROOT / 'mockups/mvp4/assets/js/service-adapters.js').read_text(encoding='utf-8')
        self.assertIn("'%s' : '%s'" % (PI.SERVICE_TOPICS[0], AP.AI_PACKAGE_TOPIC), src)
        self.assertIn("'%s' + kind" % AP.AI_PACKAGE_HEAD, src)
        self.assertIn("['%s " % AP.SERVICE_HEAD, src)                                 # companyMessage 의 첫 줄


class Screen(unittest.TestCase):
    def test_template_has_filters_but_no_hardcoded_choices(self):
        tpl = (ROOT / 'templates/admin/purchase_inquiries.html.j2').read_text(encoding='utf-8')
        body = tpl.split('{% block content %}')[1]
        for needle in ('id="piKind"', 'id="piTopic"', 'id="piSurface"', 'inquiry_kind_label', 'kind_counts', 'd.filters',
                       'var my = ++seq', 'my!==seq', 'if (my===seq)', 'if (st.fromUrl){', "button[data-k=",
                       '조건에 맞는 신청이 없습니다', 'dropUrlFilters', 'role="group" aria-label'):
            self.assertIn(needle, body, needle)
        for forbidden in ('value="ai_package"', 'value="fixed"', 'value="general"', 'value="service"',
                          'value="mvp4"', 'value="unknown"', "addOpt(kindSel,'", "addOpt(topicSel,'", "addOpt(surfSel,'"):
            self.assertNotIn(forbidden, body)       # 선택지는 서버 filters 에서만(마크업으로도 · JS 로도 박지 않는다)
        self.assertNotIn('ks.textContent=', body)   # 칩을 응답마다 다시 만들지 않는다

    def test_intro_names_the_new_topics(self):
        desc = admin_page_intro.INTRO['/admin2/purchase-inquiries']['desc']
        for word in ('AI 슈퍼컴퓨터', 'AI 패키지', '기업 AI'):
            self.assertIn(word, desc)


if __name__ == '__main__':
    unittest.main()
