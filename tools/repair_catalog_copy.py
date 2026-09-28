"""Apply reviewed explanation corrections with optimistic locks and a preimage."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from api.db import engine
from api.pc_configuration_copy import explanation_digest

def main():
    p=argparse.ArgumentParser();p.add_argument('patch',type=Path);p.add_argument('--backup',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
    changes=json.loads(a.patch.read_text(encoding='utf-8'))
    with engine.begin() as c:
        rows=[]
        for x in changes:
            row=dict(c.execute(text('SELECT * FROM product_explanations WHERE source_product_code=:code FOR UPDATE'),{'code':x['code']}).mappings().one())
            if row['content']==x['content']: continue
            assert row['status']=='draft','Do not replace approved or retired copy'
            assert explanation_digest(row)==x['before_hash'],'Source changed; regenerate reviewed patch'
            rows.append((x,row))
        if a.apply and rows:
            assert a.backup and not a.backup.exists(),'A new backup path is required'
            a.backup.write_text(json.dumps([r for _,r in rows],ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            for x,_ in rows:
                c.execute(text('UPDATE product_explanations SET content=CAST(:content AS jsonb),updated_at=now() WHERE source_product_code=:code'),{'code':x['code'],'content':json.dumps(x['content'],ensure_ascii=False)})
        print(json.dumps({'changes':len(rows),'codes':[x['code'] for x,_ in rows],'applied':a.apply},ensure_ascii=False))

if __name__=='__main__':main()
