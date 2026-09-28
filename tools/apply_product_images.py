"""Attach image metadata only after every uploaded file matches its local checksum."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from api.db import engine
from api.product_images import MEDIA_BUCKET


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);parser.add_argument('--apply',action='store_true');a=parser.parse_args()
    manifest=json.loads((a.directory/'manifest.json').read_text(encoding='utf-8'))
    inventory=json.loads((a.directory/'cloud-inventory.json').read_text(encoding='utf-8-sig'))
    remote={r['name']:r for r in inventory};ready=[r for r in manifest['items'] if r['status']=='ready']
    verified=0
    for r in ready:
        for field in ('original_key','detail_key','thumbnail_key'):
            key=r[field];raw=(a.directory/key).read_bytes();obj=remote[key]
            assert len(raw)==int(obj['size']),key
            assert base64.b64encode(hashlib.md5(raw).digest()).decode()==obj['md5_hash'],key
            verified+=1
    result=dict(verified_files=verified,linked_parts=len(ready),applied=False,bucket=MEDIA_BUCKET)
    if a.apply:
        backup=a.directory/'image-assets-db-before.json'
        assert not backup.exists(),'Backup exists: do not overwrite a previous application'
        with engine.begin() as c:
            codes=[r['product_code'] for r in ready]
            before=[dict(r) for r in c.execute(text('SELECT source_product_code,content,updated_at FROM product_explanations WHERE source_product_code=ANY(:codes) ORDER BY source_product_code FOR UPDATE'),{'codes':codes}).mappings()]
            assert len(before)==len(ready)
            backup.write_text(json.dumps(before,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            assert len(json.loads(backup.read_text(encoding='utf-8')))==len(ready)
            old={r['source_product_code']:r['content'] for r in before}
            for r in ready:
                assert old[r['product_code']]['image_url']==r['source_url'],'Source image changed'
                asset={k:r[k] for k in ('original_key','detail_key','thumbnail_key','sha256','detail_sha256','crop_box','original_size','detail_size','crop_mode')}
                asset.update(bucket=MEDIA_BUCKET,prepared_at=manifest['created_at'])
                c.execute(text("UPDATE product_explanations SET content=jsonb_set(content,'{image_asset}',CAST(:asset AS jsonb)),updated_at=now() WHERE source_product_code=:code"),{'asset':json.dumps(asset),'code':r['product_code']})
        result.update(applied=True,at=datetime.now(timezone.utc).isoformat())
    (a.directory/'image-assets-apply-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
