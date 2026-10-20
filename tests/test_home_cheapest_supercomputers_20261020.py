"""/mvp4 메인 AI 슈퍼컴퓨터 하단 2칸 = 판매 중 낮은 가격순 2개 (2026-10-20 대표 「가장 저렴한 AI수퍼컴퓨터로 노출해줘」)."""
import json
import pathlib
import re
import shutil
import subprocess
import unittest

SRC = (pathlib.Path(__file__).resolve().parents[1] / 'mockups/mvp4/assets/js/supercomputer-home.js').read_text(encoding='utf-8')


class Cheapest(unittest.TestCase):
    def test_bottom_row_uses_cheapest_not_the_dell_family(self):
        self.assertIn("box.innerHTML = models(low)", SRC)
        self.assertIn('models(cached ? cheapest(cached.items) : null)', SRC)
        self.assertIn('판매 중 AI 슈퍼컴퓨터 · 낮은 가격순', SRC)
        self.assertIn('gb-model-name', SRC)                    # 각 칸에 상품명
        self.assertIn('a.href = list.length ?', SRC)           # 위 Dell 소개 버튼은 그대로 Dell 제품군

    @unittest.skipUnless(shutil.which('node'), 'node 없음')
    def test_selection_order(self):
        fn = re.search(r'function cheapest\(items\) \{.*?\n  \}', SRC, re.S).group(0)
        items = [
            {'id': '5', 'price': 9_000_000, 'saleState': 'on_sale'},
            {'id': '3', 'price': None, 'saleState': 'check'},        # 가격 미확인은 넣지 않는다
            {'id': '4', 'price': 1_000_000, 'saleState': 'stopped'},
            {'id': '9', 'price': 7_000_000, 'saleState': 'on_sale'},
            {'id': '2', 'price': 7_000_000, 'saleState': 'on_sale'},  # 같은 가격은 상품번호 순
        ]
        out = subprocess.run(['node', '-e', fn + f';console.log(JSON.stringify(cheapest({json.dumps(items)}).map(p=>p.id)))'],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), ['2', '9'])
        one = subprocess.run(['node', '-e', fn + ";console.log(JSON.stringify(cheapest([{id:'1',price:5,saleState:'on_sale'},{id:'2',price:null,saleState:'check'}]).map(p=>p.id)))"],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(one), ['1'])


if __name__ == '__main__':
    unittest.main()
