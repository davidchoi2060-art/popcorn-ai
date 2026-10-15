"""C04-F03: 부품 설명의 GPU 모델이 시리즈(「RTX 50」)가 아니라 실제 모델이어야 한다."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIG = _load('db/migrations/versions/0157_gpu_model_fact_fix.py', 'mig_0157')
SEED = json.loads((ROOT / 'db/migrations/data/part_explanations_20260928.json').read_text(encoding='utf-8'))
GPUS = [r for r in SEED['items'] if r['content']['slot'] == 'GPU']


def model(content):
    return next((f['value'] for f in content['facts'] if f['label'] == 'GPU 모델'), None)


class GpuModelFix(unittest.TestCase):
    def test_seed_series_values_become_the_named_model(self):
        fixed = 0
        for r in GPUS:
            fix = MIG.corrected(r['content'], r['snapshot']['spec'])
            if not fix:
                continue
            out, old, new = fix
            fixed += 1
            with self.subTest(code=r['code']):
                self.assertTrue(MIG.SERIES.fullmatch(old))
                self.assertIn(new, r['content']['name'])
                self.assertEqual(model(out), new)
                self.assertIn('GPU 모델 ' + new, out['summary'])
                self.assertIn('GPU 모델: ' + new, out['highlights'])
                self.assertNotIn('GPU 모델: ' + old, out['highlights'])
                self.assertIsNone(MIG.corrected(out, r['snapshot']['spec']))  # 한 번만 고친다
                self.assertEqual(model(r['content']), old)  # 원본을 바꾸지 않는다
        self.assertEqual(fixed, 26)

    def test_rows_without_a_model_cell_are_left_alone(self):
        for r in GPUS:
            if model(r['content']) is None:
                with self.subTest(code=r['code']):
                    self.assertIsNone(MIG.corrected(r['content'], r['snapshot']['spec']))

    def test_builder_extracts_the_model_not_the_series(self):
        build = _load('tools/build_part_explanations.py', 'build_part_explanations')
        for r in GPUS:
            got = next((f['value'] for f in build.extract('GPU', r['snapshot']['spec']) if f['label'] == 'GPU 모델'), None)
            with self.subTest(code=r['code']):
                if got is not None:
                    self.assertFalse(MIG.SERIES.fullmatch(got))
                    self.assertIn(got, r['content']['name'])


if __name__ == '__main__':
    unittest.main()
