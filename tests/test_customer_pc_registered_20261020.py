"""부품표가 승인되지 않은 판매 PC 의 몰 등록 구성 읽기 (2026-10-20 대표 「부품표도 채워서 넣어」)."""
import pathlib
import unittest

from api import customer_pc_registered as R

SST = ("윈도우(OS)@@<font color=#D8D8D8><strong>[윈도우]</strong>를 선택하세요.</font> ,@@프로세서(CPU)@@<strong>[인텔]</strong> i3 12세대 12100 [Turbo 4.3GHz]™ ,"
       "@@CPU쿨러@@<strong>[OHs]</strong> CV-420 화이트 ,@@메모리(RAM)@@<strong>[삼성전자]</strong> DDR4 8G PC4-25600 *2개 ,"
       "@@대용량(HDD)@@<font color=#D8D8D8><strong>[하드디스크]</strong>를 선택하세요.</font> ,@@케이스@@[DARKFLASH] DMO11 화이트 ,"
       "@@사은품@@<font color=blue>팝콘피씨 게이밍 장패드</font> ,@@조립비+AS@@제작 및 3년 하드웨어 무상서비스 ,@@")


class Rows(unittest.TestCase):
    def test_parts_in_order_without_unselected_or_gifts(self):
        parts, service = R.rows(SST)
        self.assertEqual([p['slot'] for p in parts], ['CPU', 'RAM', 'COOLER', 'CASE'])
        self.assertEqual(parts[0]['name'], '[인텔] i3 12세대 12100 [Turbo 4.3GHz]')
        self.assertEqual(parts[1]['quantity'], 2)
        self.assertEqual(service, '제작 및 3년 하드웨어 무상서비스')

    def test_same_option_text_gives_same_key(self):
        self.assertEqual(R.key('[삼성전자] DDR4 8G  PC4-25600'), R.key('[삼성전자] DDR4 8G PC4-25600'))

    def test_unreadable_is_empty(self):
        self.assertEqual(R.rows(None), ([], None))
        self.assertEqual(R.rows('그냥 문장'), ([], None))



def _index(*rows):
    out = {}
    for i, (slot, name, selling) in enumerate(rows):
        out.setdefault(slot, []).append((1000 + i, R.norm(name), selling, R.toks(name)))
    return out


IDX = _index(("CPU", "AMD 라이젠5-6세대 9600X (그래니트 릿지)(정품)", True),
             ("CPU", "AMD 라이젠5-6세대 9600 (그래니트 릿지)(멀티팩(정품))", True),
             ("SSD", "마이크론 Crucial T500 M.2 NVMe 대원씨티에스 (2TB)", True),
             ("SSD", "마이크론 Crucial T500 M.2 NVMe 대원씨티에스 (1TB)", True),
             ("CASE", "마이크로닉스 Master M60 MESH 화이트", True),
             ("CASE", "마이크로닉스 Master M60 MESH 블랙", True),
             ("HDD", "Seagate BarraCuda HDD ST4000DM004 (4TB)", True),
             ("MB", "ASRock Z890 Pro RS WiFi 대원씨티에스", True),
             ("MB", "ASRock Z890 Pro RS WiFi 화이트 대원씨티에스", True),
             ("CASE", "마이크로닉스 Master M60 MESH", True),
             ("CPU", "인텔 코어 울트라5 시리즈2 225F (애로우레이크)(정품)", True))


class ByName(unittest.TestCase):
    """2026-10-20 실서버 집계에서 사진이 비던 문구 — 같은 모델·용량·색만 붙는다."""

    def test_model_token_must_match_exactly(self):
        self.assertEqual(R.by_name(IDX, "CPU", "[AMD] 라이젠5 그래니트 릿지 9600 [Turbo 5.2GHz, 6코어/12쓰레드]"), 1001)
        self.assertIsNone(R.by_name(IDX, "CPU", "[AMD] 라이젠7 그래니트 릿지 9700X [Turbo 5.5GHz]"))

    def test_capacity_and_sale_tags(self):
        self.assertEqual(R.by_name(IDX, "SSD", "[마이크론] Crucial T500 M.2 NVMe 2TB"), 1002)
        self.assertEqual(R.by_name(IDX, "SSD", "[마이크론] Crucial T500 M.2 NVMe 1TB HIT"), 1003)

    def test_colour(self):
        self.assertEqual(R.by_name(IDX, "CASE", "[마이크로닉스] Master M60 MESH 블랙 HIT"), 1009)  # 색 없는 이름(검정 기본)이 더 짧다
        self.assertNotEqual(R.by_name(IDX, "CASE", "[마이크로닉스] Master M60 MESH 블랙"), 1004)
        self.assertEqual(R.by_name(IDX, "MB", "[ASRock] Z890 Pro RS WiFi 화이트"), 1008)
        self.assertEqual(R.by_name(IDX, "MB", "[ASRock] Z890 Pro RS WiFi"), 1007)

    def test_generation_words_differ(self):
        self.assertEqual(R.by_name(IDX, "CPU", "[인텔] 15세대 코어 울트라5 225F [Turbo 4.9GHz, 10코어(6+4), VGA 미탑재]"), 1010)
        self.assertEqual(R.by_name(IDX, "SSD", "[마이크론] Crucial T500 1TB"), 1003)

    def test_model_code_alone(self):
        self.assertEqual(R.by_name(IDX, "HDD", "Seagate 4TB Barracuda ST4000DM004 (SATA3/5400/256M) HIT"), 1006)

    def test_built_in_parts(self):
        for slot, name in (("GPU", "[AMD] Radeon Graphics"), ("GPU", "[인텔] UHD Graphics"),
                           ("COOLER", "[AMD] 라이젠 프로세서에 포함"), ("COOLER", "인텔/AMD 정품 쿨러")):
            self.assertTrue(R._BUILT_IN[slot].search(name), name)
        self.assertFalse(R._BUILT_IN["GPU"].search("[NVIDIA] 테슬라 H100 NVL 188GB 제조사OEM"))



class Endpoint(unittest.TestCase):
    """응답 전체 경로 — 2026-10-20 names() 가 빠져 몰 등록 구성 대부분이 500 이던 회귀를 막는다."""

    def test_registered_runs_end_to_end(self):
        from unittest import mock
        sst = ("프로세서(CPU)@@[AMD] 라이젠5 그래니트 릿지 9600 [Turbo] ,@@그래픽(VGA)@@[AMD] Radeon Graphics ,"
               "@@초고속(SSD)@@[마이크론] Crucial T500 M.2 NVMe 2TB ,@@케이스@@[마이크로닉스] Master M60 MESH 블랙 HIT ,@@")

        class Res(list):
            def mappings(self): return self
            def first(self): return self[0] if self else None
            def all(self): return list(self)

        class Conn:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, q, p=None):
                q = str(q)
                if "PC_COMPLETE" in q:
                    return Res([{"product_code": 1, "status": "판매중", "spec_source_text": sst}])
                if "part_type = ANY" in q:
                    return Res([(5, "AMD 라이젠5-6세대 9600 (그래니트 릿지)", "CPU", "판매중"),
                                (6, "마이크론 Crucial T500 M.2 NVMe (2TB)", "SSD", "판매중")])
                return Res([])

        R._cache.update(at=0.0, lex={}, names={})
        with mock.patch.object(R, "engine") as e:
            e.connect.return_value = Conn()
            body = R.registered(1, mock.Mock(headers={}))
        photos = {p["slot"]: p["photo"] for p in body["parts"]}
        self.assertEqual(photos["CPU"], R.MALL_IMG.format(d=0, c=5))
        self.assertEqual(photos["GPU"], photos["CPU"])
        self.assertEqual(photos["SSD"], R.MALL_IMG.format(d=0, c=6))
        # DB·몰 어디에도 없는 케이스는 대표 사진 + 「내부 부품은 포함 구성이 아님」 안내
        case = next(p for p in body["parts"] if p["slot"] == "CASE")
        self.assertEqual(case["photo"], "assets/images/parts/micronics-master-m60-black.jpg")
        self.assertIn("포함 구성이 아닙니다", case["role"])
        root = pathlib.Path(__file__).resolve().parents[1] / "mockups" / "mvp4"
        self.assertTrue((root / case["photo"]).is_file())


if __name__ == '__main__':
    unittest.main()
