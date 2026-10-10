"""/api/talk/parse 고객 응답에 프로바이더·모델·비용·토큰이 실리지 않는다 (PR #2 계약, 2026-10-08).

parse 는 LLM·DB·방문자 한도를 함께 타서 실행 검사가 무겁다. 계약은 «응답 dict 의 키»와
«502 안내문이 원문을 끼워 넣지 않는가»라서 소스 구조(AST)로 고정한다.
"""
import ast
import inspect
import unittest

from api import talk

FORBIDDEN = {"provider", "model", "cost_usd", "tokens_in", "tokens_out",
             "answer_provider", "answer_model", "answer_cost_usd"}


def _parse_fn():
    tree = ast.parse(inspect.getsource(talk))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                and any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "post"
                        and d.args and getattr(d.args[0], "value", None) == "/parse"
                        for d in n.decorator_list))


class TalkParseNoLlmMetaTest(unittest.TestCase):
    def test_response_keys_exclude_llm_meta(self):
        fn = _parse_fn()
        dicts = [r.value for r in ast.walk(fn) if isinstance(r, ast.Return) and isinstance(r.value, ast.Dict)]
        self.assertTrue(dicts)
        for d in dicts:
            keys = {k.value for k in d.keys if isinstance(k, ast.Constant)}
            self.assertFalse(keys & FORBIDDEN, keys & FORBIDDEN)

    def test_answer_error_is_coarse_code(self):
        fn = _parse_fn()
        ret = next(r.value for r in ast.walk(fn) if isinstance(r, ast.Return) and isinstance(r.value, ast.Dict))
        value = next(v for k, v in zip(ret.keys, ret.values)
                     if isinstance(k, ast.Constant) and k.value == "answer_error")
        self.assertIsInstance(value, ast.IfExp)
        self.assertEqual(ast.unparse(value.body), "ANSWER_UNAVAILABLE")
        self.assertEqual(talk.ANSWER_UNAVAILABLE, "answer_unavailable")

    def test_502_details_are_fixed_messages(self):
        fn = _parse_fn()
        for call in ast.walk(fn):
            if (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "HTTPException"
                    and call.args and getattr(call.args[0], "value", None) == 502):
                detail = call.args[1]
                self.assertIsInstance(detail, ast.Name, ast.unparse(detail))
                self.assertIn(detail.id, ("PARSE_FAILED", "PARSE_FAILED_LIMIT"))
        for text in (talk.PARSE_FAILED, talk.PARSE_FAILED_LIMIT):
            for word in ("provider", "프로바이더", "model", "token", "cost"):
                self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
