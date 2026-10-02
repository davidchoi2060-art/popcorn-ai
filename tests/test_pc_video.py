import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from uuid import uuid4
from fastapi import HTTPException
from pydantic import ValidationError
from api import pc_video as v,pc_video_render as r

class VideoTests(unittest.TestCase):
    def test_ranges_for_seek_and_suffix(self):
        self.assertEqual(v.byte_range(None,100),(0,99,False))
        self.assertEqual(v.byte_range('bytes=20-40',100),(20,40,True))
        self.assertEqual(v.byte_range('bytes=80-',100),(80,99,True))
        self.assertEqual(v.byte_range('bytes=-10',100),(90,99,True))
        self.assertEqual(v.byte_range('bytes=0-999',100),(0,99,True))

    def test_invalid_ranges_never_return_wrong_partial_content(self):
        for s in ('bytes=100-','bytes=50-20','bytes=-0','bytes=-','bytes=0-1,3-4','invalid'):
            with self.subTest(s=s),self.assertRaises(HTTPException) as e:v.byte_range(s,100)
            self.assertEqual(e.exception.status_code,416)
            self.assertEqual(e.exception.headers['Content-Range'],'bytes */100')

    def test_input_cannot_supply_paths_templates_or_unknown_music(self):
        for extra in ({'music':'../../file'},{'template':'untrusted'}):
            with self.assertRaises(ValidationError):v.Generate(request_id=uuid4(),basis='a'*64,**extra)

    def test_data_cannot_inject_subtitle_commands(self):
        self.assertNotIn('\\',r.safe('{\\pos(1,1)}hello\nworld'))
        self.assertNotIn('{',r.safe('{override}'))

    def test_long_names_fit_canvas(self):
        value,size=r.lines('AMD Ryzen Threadripper PRO 9995WX '+('long '*8),170)
        self.assertLess(size,170)
        self.assertLessEqual(len(value.split(r'\N')),2)

    def test_approved_style_and_actual_snapshot_no_fps_promises(self):
        data=dict(configuration_id='X',title='업무용 구성',facts=dict(cpu='CPU actual',gpu='GPU actual',ram_gb=64,storage_gb=2000),cooling='수랭')
        text=r.subtitles(data)
        for s in ('CPU actual','GPU actual','64GB','SSD 2TB','수랭','AI 조립 예시','0:00:10.00',',1,5,0,7,'):
            self.assertIn(s,text)
        self.assertNotIn('RTX 5060',text);self.assertNotIn('FPS',text)

    def test_cloud_file_is_read_back_and_checksum_verified(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'v';p.write_bytes(b'video')
            session=MagicMock();session.__enter__.return_value=session;session.post.return_value.status_code=200;session.get.return_value.content=b'video'
            with patch.object(v.media,'cloud_session',return_value=session):
                self.assertEqual(v.upload_file('job','intro.mp4',p,'video/mp4')['size'],5)
                session.get.return_value.content=b'wrong'
                with self.assertRaises(ValueError):v.upload_file('job','intro.mp4',p,'video/mp4')
            self.assertEqual(session.post.call_args.kwargs['params']['ifGenerationMatch'],'0')

    def test_source_requires_owned_path_and_exact_checksum(self):
        with self.assertRaises(ValueError):v.read_source(dict(bucket='external',key='x'),'job')
        session=MagicMock();session.__enter__.return_value=session;session.get.return_value.content=b'wrong'
        with patch.object(v.media,'cloud_session',return_value=session),self.assertRaises(ValueError):
            v.read_source(dict(bucket=v.media.MEDIA_BUCKET,key='pc-configurations/job/representative.png',sha256='a'*64),'job')

if __name__=='__main__':unittest.main()
