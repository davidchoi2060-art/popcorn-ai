"""Read-only full BOM audit; save evidence, never approve products implicitly."""
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from api.db import engine
from api.pc_configuration_review import assess
from api.pc_configuration_copy import explanation_digest
from api.part_explanations import is_current
from api.pc_configuration_parts_edit import capacity
from api.pc_review_specs import specs_for_review


def collect():
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
        c.execute(text('SET TRANSACTION READ ONLY'))
        def query(sql):
            return [dict(r) for r in c.execute(text(sql)).mappings()]
        configs=query('SELECT * FROM pc_configurations ORDER BY configuration_id')
        parts=query('SELECT * FROM pc_configuration_parts ORDER BY configuration_id,ordinal')
        offers=query('SELECT * FROM pc_configuration_offers ORDER BY configuration_id,offer_id')
        rows=query('''SELECT e.*,p.product_name,p.spec_source_text,p.status AS sale_status,p.sale_price
            FROM product_explanations e LEFT JOIN products p USING(product_code)
            WHERE EXISTS(SELECT 1 FROM pc_configuration_parts b WHERE b.explanation_code=e.source_product_code)
            ORDER BY e.source_product_code''')
        specs=query('''SELECT * FROM product_specs WHERE product_code IN
            (SELECT product_code FROM product_explanations WHERE source_product_code IN
            (SELECT explanation_code FROM pc_configuration_parts)) ORDER BY product_code''')
        rules=query('SELECT * FROM compat_rules WHERE active ORDER BY rule_id')
        products=query('''SELECT product_code,product_name,status,sale_price,part_type,updated_at
            FROM products WHERE product_code IN (SELECT product_code FROM product_explanations
            WHERE source_product_code IN (SELECT explanation_code FROM pc_configuration_parts))
            OR product_code::text IN (SELECT regexp_replace(offer_id,'^P','') FROM pc_configuration_offers
            WHERE offer_id LIKE 'P%') ORDER BY product_code''')
        return dict(at=datetime.now(timezone.utc).isoformat(),configs=configs,parts=parts,offers=offers,
                    rows=rows,specs=specs,rules=rules,products=products)


def analyze(data):
    rows={r['source_product_code']:r for r in data['rows']}
    by_product={r['product_code']:r for r in data['specs']}
    specs=specs_for_review(rows,by_product)
    parts,offers,used=defaultdict(list),defaultdict(list),defaultdict(set)
    for p in data['parts']:
        parts[p['configuration_id']].append(p)
        if not p['pseudo']: used[p['explanation_code']].add(p['configuration_id'])
    for o in data['offers']: offers[o['configuration_id']].append(o)
    results=[]
    products={str(p['product_code']):p for p in data.get('products',[])}
    for cfg in data['configs']:
        key=cfg['configuration_id']
        state=assess(cfg,parts[key],offers[key],rows,specs,data['rules'])
        fail=[x for x in state['checks'] if x['state']=='fail']
        unknown=[x for x in state['checks'] if x['state']=='unknown' and x.get('stage','recommendation')=='recommendation']
        structural=[];price_notes=[]
        for slot in ('CPU','RAM','SSD','MB','POWER','CASE'):
            if not any(p['slot']==slot and not p['pseudo'] for p in parts[key]): structural.append(slot+' 실제 구성 누락')
        for slot,fact,label in [('RAM','ram_gb','상품 용량'),('SSD','storage_gb','용량')]:
            quantities=[]
            for p in parts[key]:
                if p['slot']!=slot or p['pseudo']: continue
                f={x['label']:x['value'] for x in rows.get(p['explanation_code'],{}).get('content',{}).get('facts',[])}
                v=capacity(f.get(label));quantities.append(None if v is None else v*p['quantity'])
            if not quantities or any(v is None for v in quantities): structural.append(slot+' 용량 대조 근거 부족')
            elif sum(quantities)!=cfg['content'].get('facts',{}).get(fact): structural.append(slot+' BOM 용량과 상품 설명 불일치')
        sale_states=[]
        for o in offers[key]:
            if o['price_snapshot'] is None or o['price_snapshot']<=0: structural.append('유효한 기준 가격 없음')
            if o['offer_id'].startswith('P'):
                prod=products.get(o['offer_id'][1:])
                sale_states.append(prod['status'] if prod else 'DB 연결 없음')
                if prod and prod['sale_price']!=o['price_snapshot']: price_notes.append(f"{o['offer_id']} 저장가 {o['price_snapshot']} / DB 판매가 {prod['sale_price']} · 옵션 기준 대조")
            else:
                unit=[rows.get(p['explanation_code'],{}).get('sale_price') for p in parts[key] if not p['pseudo']]
                if all(v is not None and v>0 for v in unit):
                    total=sum(rows[p['explanation_code']]['sale_price']*p['quantity'] for p in parts[key] if not p['pseudo'])+o['payload'].get('assembly_fee_added',0)
                    if total!=o['price_snapshot']: price_notes.append(f"부품+기존 조립비 {total} / 저장가 {o['price_snapshot']}")
                else: price_notes.append('현재 단품 합계 산출 근거 부족')
        excluded=bool(fail) or cfg['status']=='retired' or any('판매중 부품 아님' in x for x in state['blockers']) or (bool(sale_states) and all(x not in ('판매중','DB 연결 없음') for x in sale_states))
        group='제외 대상' if excluded else '보완 필요' if state['blockers'] or unknown or structural or price_notes or 'DB 연결 없음' in sale_states else '조건부 추천 후보' if state.get('assembly_checks') else '추천 가능 후보'
        results.append(dict(id=key,title=cfg['content'].get('title'),source=cfg['content'].get('source'),
            facts=cfg['content'].get('facts'),group=group,review=state,offers=offers[key],
            failed=fail,unknown=unknown,part_count=len(parts[key]),structural=structural,price_notes=price_notes,sale_states=sale_states))
    common=[]
    for code,ids in used.items():
        r=rows.get(code)
        reasons=[]
        if not r: reasons.append('설명 없음')
        else:
            if r['content'].get('review_issues'): reasons += r['content']['review_issues']
            if r.get('product_code') is not None and not is_current(r): reasons.append('상품 원문과 설명 근거 불일치')
            if r.get('product_code') is not None and r.get('sale_status')!='판매중': reasons.append('판매중 부품 아님')
            if any(p['explanation_hash']!=explanation_digest(r) for p in data['parts'] if p['explanation_code']==code and not p['pseudo']): reasons.append('BOM의 설명 해시와 현재 설명 불일치')
        common.append(dict(code=code,name=r['content'].get('name') if r else '',slot=r['content'].get('slot') if r else '',
            count=len(ids),configurations=sorted(ids),issues=reasons,source_current=is_current(r) if r and r['product_code'] else None))
    return dict(at=data['at'],counts=dict(Counter(r['group'] for r in results)),total=len(results),
                unique_parts=len(used),configurations=results,common_parts=sorted(common,key=lambda r:(-r['count'],r['code'])))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);args=p.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    data=collect(); result=analyze(data)
    for name,value in [('source.json',data),('audit.json',result)]:
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('at','counts','total','unique_parts')},ensure_ascii=False))
    print(json.dumps([r for r in result['common_parts'] if r['issues']],ensure_ascii=False))
