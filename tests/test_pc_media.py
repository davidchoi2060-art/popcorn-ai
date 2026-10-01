import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from PIL import Image
from api import pc_media as m
from api.pc_configuration_copy import digest

class MediaTests(unittest.TestCase):
    def test_visual_basis_changes_with_quantity_cooler_or_image_but_not_price(self):
        parts=[dict(slot='CASE',explanation_code=1,quantity=1)]
        rows={1:dict(content=dict(name='case',facts=[],image_asset=dict(detail_sha256='a')),sale_price=1)}
        a=m.visual_snapshot(parts,rows,dict(installed='separate',method_label='공랭'))
        rows[1]['sale_price']=100
        self.assertEqual(digest(a),digest(m.visual_snapshot(parts,rows,dict(installed='separate',method_label='공랭'))))
        rows[1]['content']['image_asset']['detail_sha256']='b'
        self.assertNotEqual(digest(a),digest(m.visual_snapshot(parts,rows,dict(installed='separate',method_label='공랭'))))
        self.assertNotEqual(digest(a),digest(m.visual_snapshot(parts,rows,dict(installed='separate',method_label='수랭'))))
        parts[0]['quantity']=2
        self.assertNotEqual(digest(a),digest(m.visual_snapshot(parts,rows,dict(installed='separate',method_label='공랭'))))

    def test_prompt_case_and_no_fabricated_led(self):
        s=m.prompt(dict(parts=[],cooling={}))
        for text in ['exact CASE','never invent transparent panels','never both','do not invent RGB','no text']:
            self.assertIn(text,s)

    def test_missing_output_does_not_silently_succeed(self):
        client=MagicMock();client.__enter__.return_value=client;client.models.generate_content.return_value.parts=[]
        with patch('google.genai.Client',return_value=client),patch.dict(m.os.environ,{'GEMINI_API_KEY':'test'}):
            with self.assertRaises(ValueError):m.generate_image(dict(parts=[],cooling={}),m.MODEL)
        self.assertEqual(client.models.generate_content.call_count,1)

    def test_provider_image_normalized_without_automatic_fallback(self):
        raw=io.BytesIO();Image.new('RGB',(4,4),'white').save(raw,'JPEG')
        part=MagicMock();part.inline_data.data=raw.getvalue();part.inline_data.mime_type='image/jpeg'
        client=MagicMock();client.__enter__.return_value=client;client.models.generate_content.return_value.parts=[part]
        with patch('google.genai.Client',return_value=client),patch.dict(m.os.environ,{'GEMINI_API_KEY':'test'}):out=m.generate_image(dict(parts=[],cooling={}),m.MODEL)
        self.assertTrue(out.startswith(b'\x89PNG'));self.assertEqual(client.models.generate_content.call_count,1)

    def test_storage_conflict_only_reuses_identical_bytes(self):
        response=MagicMock(status_code=412);existing=MagicMock();existing.content=b'image'
        session=MagicMock();session.__enter__.return_value=session;session.post.return_value=response;session.get.return_value=existing
        with patch.object(m,'cloud_session',return_value=session):
            self.assertEqual(m.upload(dict(job_id='job'),b'image')['sha256'],m.hashlib.sha256(b'image').hexdigest())
            with self.assertRaises(ValueError):m.upload(dict(job_id='job'),b'changed')
        self.assertEqual(session.post.call_args.kwargs['params']['ifGenerationMatch'],'0')
