"""Apply only additive 0116 after snapshotting the affected cohort; dry-run default."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from api.db import engine

def main():
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    seed=root/'db/migrations/data/part_explanations_20260928.json'
    data=json.loads(seed.read_text(encoding='utf-8'));codes=[x['code'] for x in data['items']]
    with engine.connect() as c:
        before_head=c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
        exists=c.execute(text("SELECT to_regclass('public.product_explanations')")).scalar()
        before=[dict(r) for r in c.execute(text('SELECT product_code,product_name,spec_source_text,status,sale_price,ai_candidate_yn,review_required_yn FROM products WHERE product_code=ANY(:codes) ORDER BY product_code'),{'codes':codes}).mappings()]
    assert before_head=='0115' and exists is None,'Expected untouched 0115; do not replay or overwrite existing content'
    result={'at':datetime.now(timezone.utc).isoformat(),'seed_sha256':hashlib.sha256(seed.read_bytes()).hexdigest(),'before_head':before_head,'new_draft_count':len(codes),'linked_existing_products':len(before),'applied':False}
    a.output.mkdir(parents=True,exist_ok=True)
    backup=a.output/'part-explanations-before.json'
    backup.write_text(json.dumps({'summary':result,'products':before},ensure_ascii=False,indent=2),encoding='utf-8')
    assert json.loads(backup.read_text(encoding='utf-8'))['products']==before
    if a.apply:
        cfg=Config(str(root/'db/alembic.ini'));cfg.set_main_option('script_location',str(root/'db/migrations'))
        command.upgrade(cfg,'0116')
        with engine.connect() as c:
            result['head']=c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
            result['counts']=dict(c.execute(text("SELECT count(*) AS total, count(*) FILTER(WHERE status='draft') AS drafts, count(*) FILTER(WHERE product_code IS NULL) AS unlinked FROM product_explanations")).mappings().one())
            after=[dict(r) for r in c.execute(text('SELECT product_code,product_name,spec_source_text,status,sale_price,ai_candidate_yn,review_required_yn FROM products WHERE product_code=ANY(:codes) ORDER BY product_code'),{'codes':codes}).mappings()]
        assert result['head']=='0116' and result['counts']['total']==len(codes) and result['counts']['drafts']==len(codes)
        assert before==after,'Existing product values changed during operation; inspect concurrent writes'
        result.update(applied=True,existing_products_unchanged=True)
    (a.output/'part-explanations-apply-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
