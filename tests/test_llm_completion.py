"""Provider completion metadata without network calls or database writes."""
import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from api import llm


class CompletionTests(unittest.TestCase):
    def test_gemini_limit_with_partial_or_empty_text_preserves_usage(self):
        from google import genai
        from google.genai import types
        for text in ('{"changes":', None):
            response = SimpleNamespace(text=text,
                candidates=[SimpleNamespace(finish_reason=types.FinishReason.MAX_TOKENS)],
                usage_metadata=SimpleNamespace(prompt_token_count=100,
                    candidates_token_count=20, thoughts_token_count=80))
            client = MagicMock()
            client.models.generate_content.return_value = response
            with self.subTest(text=text), patch.object(genai, 'Client', return_value=client):
                result = llm._call_gemini('fixture-model', 'fixture', None, 100, 5)
                self.assertEqual(tuple(result), (text or '', 100, 100))
                self.assertEqual(result.finish_reason, 'MAX_TOKENS')
                client.models.generate_content.assert_called_once()

    def test_gemini_normal_and_blocked_responses(self):
        from google import genai
        for reason, text, expected in [('STOP','{}','STOP'),
                                       ('PRIVATE-UNEXPECTED','{}','OTHER')]:
            client = MagicMock()
            client.models.generate_content.return_value = SimpleNamespace(
                text=text,candidates=[SimpleNamespace(finish_reason=reason)],usage_metadata=None)
            with patch.object(genai,'Client',return_value=client):
                self.assertEqual(llm._call_gemini('fixture','fixture',None,100,5).finish_reason,expected)
        client.models.generate_content.return_value = SimpleNamespace(
            text=None,candidates=[SimpleNamespace(finish_reason='SAFETY')],usage_metadata=None)
        with patch.object(genai,'Client',return_value=client), self.assertRaises(llm.LLMProviderError):
            llm._call_gemini('fixture','fixture',None,100,5)

    def test_billable_limit_is_logged_once_and_old_tuple_adapter_still_works(self):
        for response in [llm.ProviderResponse('',100,90,'MAX_TOKENS'), ('{}',100,90)]:
            caller=MagicMock(return_value=response)
            spec=replace(llm.PROVIDERS['gemini'],caller=caller)
            engine=MagicMock()
            engine.begin.return_value.__enter__.return_value.execute.return_value.scalar_one.return_value=123
            with patch.dict(llm.PROVIDERS,{'gemini':spec}), patch.dict(os.environ,{spec.env_key:'fixture-key'}), patch.object(llm,'engine',engine), patch.object(llm,'_check_caps'):
                result=llm._call_one('fixture','gemini',None,None,None,False,100,5)
            caller.assert_called_once()
            engine.begin.return_value.__enter__.return_value.execute.assert_called_once()
            self.assertEqual(result.log_id,123)
            self.assertTrue(result.cost_logged)
            self.assertEqual(result.finish_reason,'MAX_TOKENS' if isinstance(response,llm.ProviderResponse) else None)


if __name__=='__main__':unittest.main()
