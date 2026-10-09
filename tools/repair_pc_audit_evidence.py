"""Apply explicit audited source repairs with backups and optimistic checks."""
import argparse, copy, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from api.db import engine
from api.pc_configuration_copy import digest, explanation_digest
from api.part_explanations import fingerprint
from tools.build_part_explanations import extract

FACT_CODES={108494,110212,113969,113970,128462}
SPEC_REPAIRS={
 129551:dict(cooler_height_mm=75,gpu_max_mm=240,form_factor_list=['m-ATX','mini-ITX']),
 129552:dict(cooler_height_mm=75,gpu_max_mm=240,form_factor_list=['m-ATX','mini-ITX']),
 129775:dict(mem_type='DDR5'),
 114723:dict(socket_list=['AM4','AM5','LGA115(X)','LGA1200','LGA1700','LGA1851']),
}
THERMAL='https://www.thermalright.com/product/peerless-assassin-120-se-white-argb/'

def apply(c,source):
    c.execute(text("SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))"))
    before_rows={r['source_product_code']:r for r in source['rows']}
    before_specs={r['product_code']:r for r in source['specs']}
    before_configs={r['configuration_id']:r for r in source['configs']}
    changes=[];touched={}; backups=dict(explanations=[],specs=[],products=[],configurations=[])
    for code in sorted(FACT_CODES):
        row=dict(c.execute(text('SELECT * FROM product_explanations WHERE source_product_code=:code FOR UPDATE'),dict(code=code)).mappings().one())
        assert row['status']=='draft' and explanation_digest(row)==explanation_digest(before_rows[code]), 'Explanation changed'
        product=c.execute(text('SELECT product_name,spec_source_text FROM products WHERE product_code=:code FOR SHARE'),dict(code=code)).mappings().one()
        assert fingerprint(product['product_name'],product['spec_source_text'])==fingerprint(before_rows[code]['product_name'],before_rows[code]['spec_source_text']), 'Source changed'
        label='상품 용량' if row['content']['slot']=='RAM' else '용량'
        fact=next(x for x in extract(row['content']['slot'],product['spec_source_text']) if x['label']==label)
        assert not any(f['label']==label for f in row['content']['facts']), 'Capacity already present'
        content=copy.deepcopy(row['content']);content['facts'].insert(0,fact)
        content['summary']=' · '.join(f"{f['label']} {f['value']}" for f in content['facts'][:3])
        content['highlights']=[f"{f['label']}: {f['value']}" for f in content['facts'][:3]]
        content.setdefault('resolved_issues',[]).append(dict(date='2026-09-30',resolution='원문 용량 표기 추출 누락 수정',source_id='merchant',value=fact['value']))
        backups['explanations'].append(row)
        c.execute(text('UPDATE product_explanations SET content=CAST(:v AS jsonb),updated_at=now() WHERE source_product_code=:code'),dict(code=code,v=json.dumps(content,ensure_ascii=False)))
        touched[code]=explanation_digest(dict(row,content=content))
        changes.append(dict(code=code,type='설명 용량 보완',value=fact['value'],source=content['sources'][0]['url']))
    for code,updates in SPEC_REPAIRS.items():
        row=dict(c.execute(text('SELECT * FROM product_specs WHERE product_code=:code FOR UPDATE'),dict(code=code)).mappings().one())
        assert digest(row)==digest(before_specs[code]), 'Spec changed'
        prod=dict(c.execute(text('SELECT product_code,locked_fields,product_name,spec_source_text FROM products WHERE product_code=:code FOR UPDATE'),dict(code=code)).mappings().one())
        assert prod['spec_source_text']==before_rows[code]['spec_source_text'], 'Spec source changed'
        backups['specs'].append(row);backups['products'].append(prod)
        sources=dict(row.get('spec_sources') or {})
        for field,value in updates.items():
            if code!=114723: assert row[field] is None, 'Do not overwrite existing facts'
            source_url=THERMAL if code==114723 else f'https://www.popcornpc.co.kr/shop/product_detail.html?pd_no={code}'
            sources[field]='audit:2026-09-30:'+source_url
            c.execute(text(f'UPDATE product_specs SET {field}='+('CAST(:v AS jsonb)' if isinstance(value,list) else ':v')+' WHERE product_code=:code'),dict(code=code,v=json.dumps(value) if isinstance(value,list) else value))
            changes.append(dict(code=code,type='사양 보완',field=field,before=row[field],value=value,source=source_url))
        c.execute(text('UPDATE product_specs SET spec_sources=CAST(:v AS jsonb),updated_at=now() WHERE product_code=:code'),dict(code=code,v=json.dumps(sources)))
        # Audit/source values are not human-confirmed: never add them to locked_fields
        # (only the admin spec-entry path locks). The source is kept in spec_sources.
    ids=c.execute(text('SELECT DISTINCT configuration_id FROM pc_configuration_parts WHERE explanation_code=ANY(:codes) ORDER BY configuration_id'),dict(codes=sorted(touched))).scalars().all()
    for identity in ids:
        cfg=dict(c.execute(text('SELECT * FROM pc_configurations WHERE configuration_id=:id FOR UPDATE'),dict(id=identity)).mappings().one())
        assert digest(cfg)==digest(before_configs[identity]), 'Configuration changed'
        parts=[dict(r) for r in c.execute(text('SELECT * FROM pc_configuration_parts WHERE configuration_id=:id ORDER BY ordinal'),dict(id=identity)).mappings()]
        offers=[dict(r) for r in c.execute(text('SELECT * FROM pc_configuration_offers WHERE configuration_id=:id ORDER BY offer_id'),dict(id=identity)).mappings()]
        snap=dict(cfg,parts=copy.deepcopy(parts),offers=offers,edit=dict(kind='evidence_repair',name='source-audit-20260930',reason='원문에서 누락된 용량 설명 동기화; 승인/가격/BOM 유지'))
        backups['configurations'].append(snap)
        c.execute(text('INSERT INTO pc_configuration_history(configuration_id,revision,snapshot) VALUES(:id,:rev,CAST(:v AS jsonb))'),dict(id=identity,rev=cfg['revision'],v=json.dumps(snap,ensure_ascii=False,default=str)))
        for p in parts:
            if p['explanation_code'] in touched:
                p['explanation_hash']=touched[p['explanation_code']]
                c.execute(text('UPDATE pc_configuration_parts SET explanation_hash=:h WHERE configuration_id=:id AND ordinal=:n'),dict(h=p['explanation_hash'],id=identity,n=p['ordinal']))
        c.execute(text('UPDATE pc_configurations SET revision=revision+1,content_hash=:h,copy_hash=:ch,updated_at=now() WHERE configuration_id=:id'),dict(id=identity,h=digest(dict(content=cfg['content'],parts=parts,offers=offers)),ch=digest(dict(content=cfg['content'],parts=parts))))
    return dict(changes=changes,synced_configurations=ids,backups=backups)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--out',required=True);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    source=json.loads(Path(args.source).read_text(encoding='utf-8'))
    out=Path(args.out);assert not out.exists(),'New backup file required';out.parent.mkdir(parents=True,exist_ok=True)
    with engine.connect() as c:
        tx=c.begin()
        try:
            result=apply(c,source)
            # Serialized preimages exist before commit; same operation dry run always rolls back.
            out.write_text(json.dumps(dict(result,applied=args.apply),ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            if args.apply: tx.commit()
            else: tx.rollback()
        except Exception:
            tx.rollback();raise
    print(json.dumps(dict(applied=args.apply,changes=len(result['changes']),synced_configurations=len(result['synced_configurations'])),ensure_ascii=False))
