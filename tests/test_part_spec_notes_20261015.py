"""오픈테스트 C01-F01(메인보드 영상 출력 없음) · C06-F04(GPU 권장 650W vs 장착 600W 무설명) 회귀.

판매처 원문은 db/migrations/data/part_explanations_20260928.json 의 실제 스냅샷에서 옮겼다. DB 없음.
"""
import unittest

from api import part_spec_notes as N

MB_112458 = ('ASUS / 인텔 / 소켓 : LGA1700 / 칩셋 : Z790 (인텔) / ATX / DDR5 / 슬롯 : 4(EA) / M.2 : 3(EA) / '
             'SATA3 : 4(EA) / HDMI / DP / PCI-Ex. x16 : 4(EA) / USB Type A / USB Type C / RJ-45(LAN) 포트 : 1(EA) / ')
MB_113689 = '메인보드 / 제조회사 : ASRock / 폼팩터 : M-ATX / 메모리 종류 : DDR5 / DVI : DP / HDMI : HDMI / M.2 : 3 + 1개 / TYPE C : Type-C / '
MB_128825 = 'GIGABYTE / 인텔 / LGA1700 / B760 (인텔) / m-ATX / DDR4 / SATA / D-SUB / HDMI / DP / USB Type-C / PCI-Ex. x16 : 1(EA) / '
MB_122305 = 'ASRock / 인텔 / LGA1851 / Z890 (인텔) / ATX / DDR5 / USB C타입 : 2(EA) / RJ-45(LAN) 포트 : 1(EA) / 2.5기가비트 / '
GPU_123291 = ('PALIT / nVIDIA / RTX 5080 / 메모리용량 : 16(GB) / GDDR7 / 출력단자(DP) : 3(EA) / 출력단자(HDMI) : 1(EA) / '
              '8K / 정격 850(W) 이상 / 길이 : 331.9(mm) / ')


def row(slot, facts=(), spec='', cautions=(), draw=None):
    return dict(content=dict(slot=slot, facts=[dict(label=k, value=v) for k, v in facts], cautions=list(cautions)),
                source_spec=spec, gpu_power_draw_watt=draw)


class BoardOutputs(unittest.TestCase):
    def test_tokens_from_merchant_source_in_source_order(self):
        self.assertEqual(N.board_ports(MB_112458), ['HDMI', 'DP'])
        self.assertEqual(N.board_ports(MB_128825), ['D-SUB', 'HDMI', 'DP'])
        # 「DVI : DP / HDMI : HDMI」 -- 값이 단자다. USB Type-C·SATA 는 영상 단자로 세지 않는다.
        self.assertEqual(N.board_ports(MB_113689), ['DP', 'HDMI'])
        self.assertEqual(N.board_ports(MB_122305), [])

    def test_board_row_gets_output_or_explicit_unknown(self):
        out = N.derived_specs({3: row('MB', [('CPU 소켓', 'LGA1700')], MB_112458)})
        self.assertEqual(out[3], [dict(label='영상 출력', value='HDMI · DP (CPU 내장그래픽 필요 · 판매처 표기)')])
        out = N.derived_specs({3: row('MB', spec=MB_122305)})
        self.assertEqual(out[3], [dict(label='영상 출력', value='판매처 표기 없음 · 확인 필요')])

    def test_reviewer_hold_is_not_overridden_by_merchant_text(self):
        # 113685: 검수자가 판매처 DVI 표기를 확정으로 쓰지 않기로 하고 사실에서 뺐다 -- 원문으로 되살리지 않는다.
        caution = '정확한 영상 출력 단자는 출고 보드 리비전 확인 후 안내합니다. 판매처에 표기된 DVI를 지원 확정으로 사용하지 않습니다.'
        out = N.derived_specs({1: row('MB', spec='D-SUB / DVI / HDMI / ', cautions=['CPU 소켓만 같다고', caution])})
        self.assertEqual(out[1], [dict(label='영상 출력', value='확인 필요 · ' + caution)])

    def test_existing_output_fact_is_not_duplicated(self):
        self.assertEqual(N.derived_specs({1: row('MB', [('영상 출력 (rev.1.0)', 'HDMI·D-Sub')], MB_112458)}), {})

    def test_cpu_without_integrated_graphics_is_stated(self):
        rows = {0: row('CPU', [('내장그래픽', '없음')]), 3: row('MB', spec=MB_112458)}
        self.assertIn('내장그래픽이 없어 보드 단자로는 화면이 나오지 않아요', N.derived_specs(rows)[3][0]['value'])

    def test_gpu_ports_with_counts(self):
        out = N.derived_specs({2: row('GPU', spec=GPU_123291)})
        self.assertEqual(out[2], [dict(label='영상 출력', value='DP 3개 · HDMI 1개 (판매처 표기)')])

    def test_other_slots_untouched(self):
        self.assertEqual(N.derived_specs({5: row('RAM', spec='HDMI / ')}), {})


class PowerBasis(unittest.TestCase):
    def c06(self, draw=180, rated='600(W)'):
        return {2: row('GPU', [('권장 파워', '정격 650(W) 이상')], draw=draw), 7: row('POWER', [('정격 출력', rated)])}

    def note(self, rows, offset):
        return [s for s in N.derived_specs(rows, offset).get(2, []) if s['label'] == '파워 판정 기준']

    def test_c06_gap_is_explained_with_server_values(self):
        value = self.note(self.c06(), 200)[0]['value']
        self.assertIn('장착 파워 600W는 판매처 권장 650W보다 낮아요', value)
        self.assertIn('소비전력 180W + 시스템 여유 200W = 380W 기준으로 통과', value)
        self.assertIn('650W 이상 파워로 바꿔 주세요', value)

    def test_unknown_draw_or_rule_is_not_called_pass(self):
        for draw, offset in ((None, 200), (180, None)):
            value = self.note(self.c06(draw=draw), offset)[0]['value']
            self.assertIn('확정하지 못했어요', value)
            self.assertNotIn('통과', value)

    def test_below_rule_threshold_is_flagged(self):
        value = self.note(self.c06(draw=450), 200)[0]['value']
        self.assertIn('호환 기준 650W에도 못 미쳐', value)

    def test_no_note_when_psu_meets_merchant_recommendation(self):
        self.assertEqual(self.note(self.c06(rated='650(W)'), 200), [])


if __name__ == '__main__':
    unittest.main()
