"""관리자단 개선 PR-1 (2026-10-31) — 구매 상담 신청 거르기 · AI 슈퍼컴퓨터 보관 표시. DB 없이 확인하는 것.

고객 화면이 10월에 늘린 문의 주제(0165 AI 슈퍼컴퓨터 · 0174 기업 컨설팅 · /mvp4 AI 패키지)를 관리자 처리함이
가를 수 있는지, AI 장비 「견적에 저장」(#373)이 「쇼핑몰 완제품」으로 잘못 보이던 것이 고쳐졌는지,
선택지가 서버 상수에서만 오는지 본다. 실제 조회는 개발 DB(읽기 전용)로 따로 확인했다(PR 본문).
"""
import pathlib
import unittest

from fastapi import HTTPException

from api import admin_mvp3_links as L
from api import admin_page_intro
from api import admin_purchase_inquiries as AP
from api import customer_surface as cs
from api import mvp3_purchase_inquiry as PI

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXED = {'product_code': 129615, 'name': 'x', 'intent': 'quote', 'quantity': 1}


class SavedQuoteKind(unittest.TestCase):
    def test_ai_device_snapshot_is_not_a_mall_pc(self):
        snap = {'kind': 'ai_device', 'name': 'HP ZGX nano G1n', 'price': 5000000, 'product_code': 130449}
        self.assertEqual(L.kind(snap), ('ai_device', 'AI 슈퍼컴퓨터 장비'))
        self.assertEqual(L.kind({'kind': 'pc', 'name': 'x'})[0], 'mall')          # 일반 PC 보관은 그대로
        self.assertEqual(L.kind({'name': 'x'})[0], 'mall')                        # kind 를 안 적던 옛 보관도 그대로

    def test_precedence_unchanged(self):
        snap = {'kind': 'ai_device'}
        self.assertEqual(L.kind(snap, None, None, FIXED)[0], 'fixed_product')
        self.assertEqual(L.kind(snap, None, {'parts': []})[0], 'free_build')
        self.assertEqual(L.kind({'kind': 'ai_device', 'ai_composed': True})[0], 'ai_device')

    def test_consults_timeline_reads_the_same_rule(self):
        src = (ROOT / 'api/admin_mvp3_consults.py').read_text(encoding='utf-8')
        self.assertIn('L.kind(p)[1]', src)


class InquiryKind(unittest.TestCase):
    def test_four_kinds(self):
        self.assertEqual(AP.inquiry_kind('AI 슈퍼컴퓨터 견적', None, FIXED)[0], 'fixed')
        self.assertEqual(AP.inquiry_kind(PI.SERVICE_TOPICS[0], '[기업 AI 업무개선 컨설팅] 30인 이하')[0], 'service')
        self.assertEqual(AP.inquiry_kind('기타', '[AI 패키지 견적 문의] 기본형\n관심 기능: 회의록')[0], 'ai_package')
        self.assertEqual(AP.inquiry_kind('기타', '그냥 궁금해서요')[0], 'general')
        self.assertEqual(AP.inquiry_kind('여러 대 구매', None)[0], 'general')
        self.assertEqual(AP.inquiry_kind('기타', None)[0], 'general')                  # 본문 없는 「기타」 = 일반

    def test_fixed_wins_and_head_must_be_at_start(self):
        self.assertEqual(AP.inquiry_kind('기타', '[AI 패키지 견적 문의]', FIXED)[0], 'fixed')
        self.assertEqual(AP.inquiry_kind('기타', '문의: [AI 패키지 견적 문의]')[0], 'general')
        self.assertEqual(AP.inquiry_kind('할인', '[AI 패키지 견적 문의]')[0], 'general')   # 주제가 다르면 머리글만으로 가르지 않는다

    def test_purged_other_topic_says_it_cannot_tell(self):
        key, label = AP.inquiry_kind('기타', None, None, purged=True)
        self.assertEqual(key, 'general')
        self.assertIn('알 수 없음', label)
        self.assertEqual(AP.inquiry_kind('여러 대 구매', None, None, purged=True), ('general', '일반 상담'))
        self.assertEqual(AP.inquiry_kind(PI.SERVICE_TOPICS[0], None, None, purged=True)[0], 'service')

    def test_labels_come_from_one_table(self):
        for key, label in AP.INQUIRY_KINDS:
            self.assertEqual(AP.KIND_LABEL[key], label)


class SqlMirrorsPython(unittest.TestCase):
    """SQL 조건(KINDS)과 inquiry_kind() 가 같은 판정을 적는지 — 문자열로 되짚을 수 있는 만큼 본다."""
    def test_same_keys_and_partition_shape(self):
        self.assertEqual(set(AP.KINDS), {k for k, _ in AP.INQUIRY_KINDS})
        self.assertEqual(AP.KINDS['fixed'], 'i.fixed_product IS NOT NULL')
        for k in ('service', 'ai_package', 'general'):
            self.assertTrue(AP.KINDS[k].startswith('(i.fixed_product IS NULL AND '), k)

    def test_package_predicate_uses_topic_head_and_null_safe_message(self):
        self.assertIn("i.topic = '%s'" % AP.AI_PACKAGE_TOPIC, AP.KINDS['ai_package'])
        self.assertIn("COALESCE(i.message, '') LIKE '%s%%'" % AP.AI_PACKAGE_HEAD, AP.KINDS['ai_package'])
        self.assertIn("COALESCE(i.message, '')", AP.KINDS['general'])   # NULL 본문이 NOT 에서 행을 떨어뜨리지 않게
        self.assertNotIn('%', AP.AI_PACKAGE_HEAD)
        self.assertNotIn('_', AP.AI_PACKAGE_HEAD)                        # LIKE 와일드카드가 머리글에 없다

    def test_service_predicate_lists_server_topics(self):
        for t in PI.SERVICE_TOPICS:
            self.assertIn("'%s'" % t, AP.KINDS['service'])
            self.assertIn("'%s'" % t, AP.KINDS['general'])


class Choices(unittest.TestCase):
    def test_topics_are_the_customer_modules_constants(self):
        self.assertEqual(AP.TOPIC_CHOICES, tuple(PI.TOPICS) + tuple(PI.FIXED_TOPICS.values()) + tuple(PI.SERVICE_TOPICS))
        self.assertEqual(len(AP.TOPIC_CHOICES), len(set(AP.TOPIC_CHOICES)))
        self.assertIn(AP.AI_PACKAGE_TOPIC, PI.TOPICS)

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
    """AI 패키지 문의의 주제·머리글은 /mvp4 화면이 보내는 값이다 — 화면이 바뀌면 이 판정도 같이 바뀌어야 한다."""
    def test_service_adapters_send_the_topic_and_head_we_read(self):
        src = (ROOT / 'mockups/mvp4/assets/js/service-adapters.js').read_text(encoding='utf-8')
        self.assertIn("'%s' : '%s'" % (PI.SERVICE_TOPICS[0], AP.AI_PACKAGE_TOPIC), src)
        self.assertIn("'%s' + kind" % AP.AI_PACKAGE_HEAD, src)


class Screen(unittest.TestCase):
    def test_template_has_filters_but_no_hardcoded_choices(self):
        tpl = (ROOT / 'templates/admin/purchase_inquiries.html.j2').read_text(encoding='utf-8')
        for needle in ('id="piKind"', 'id="piTopic"', 'id="piSurface"', 'inquiry_kind_label', 'kind_counts', 'd.filters'):
            self.assertIn(needle, tpl)
        for forbidden in ('value="ai_package"', 'value="fixed"', 'value="general"', 'value="service"',
                          'value="mvp4"', 'value="unknown"'):
            self.assertNotIn(forbidden, tpl)       # 선택지는 서버 filters 에서만

    def test_intro_names_the_new_topics(self):
        desc = admin_page_intro.INTRO['/admin2/purchase-inquiries']['desc']
        for word in ('AI 슈퍼컴퓨터', 'AI 패키지', '기업 AI'):
            self.assertIn(word, desc)


if __name__ == '__main__':
    unittest.main()
