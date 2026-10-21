"""기업 AI 업무개선 컨설팅 상담은 고유 주제로 저장한다 (0174, 2026-10-21 대표)."""
import pathlib
import unittest

from fastapi import HTTPException

import api.mvp3_purchase_inquiry as PI

ROOT = pathlib.Path(__file__).resolve().parents[1]


def body(**kw):
    base = dict(topic='기업 AI 업무개선 컨설팅', name='시험', phone='010-0000-0000', message='[기업 AI 업무개선 컨설팅]', consent=True, client_key='abcdef12')
    base.update(kw)
    return PI.InquiryBody(**base)


class CompanyTopic(unittest.TestCase):
    def test_accepted_but_not_in_general_list(self):
        self.assertEqual(PI._clean(body())[0], '010-0000-0000')
        self.assertNotIn('기업 AI 업무개선 컨설팅', PI.TOPICS)

    def test_rejects_product_or_quote(self):
        for extra in ({'product_code': 113835}, {'configuration_id': 'A0123456789ABCDEF'}):
            with self.assertRaises(HTTPException):
                PI._clean(body(**extra))

    def test_migration_adds_value_and_keeps_old(self):
        m = (ROOT / 'db/migrations/versions/0174_purchase_inquiry_company_consulting.py').read_text(encoding='utf-8')
        self.assertIn("revision = '0174'", m)
        self.assertIn("down_revision = '0173'", m)
        self.assertIn("'AI 도입 상담','기업 AI 업무개선 컨설팅'", m)
        self.assertIn('RAISE EXCEPTION', m)   # 새 주제 행이 있으면 되돌리지 않는다

    def test_screen_sends_company_topic_only_for_company(self):
        s = (ROOT / 'mockups/mvp4/assets/js/service-adapters.js').read_text(encoding='utf-8')
        self.assertIn("topic: p.service === 'company' ? '기업 AI 업무개선 컨설팅' : '기타'", s)


if __name__ == '__main__':
    unittest.main()
