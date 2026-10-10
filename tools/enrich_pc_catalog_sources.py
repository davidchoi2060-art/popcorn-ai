"""Source-reviewed additions only; dry-run by default, with preimages before commit."""
import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from api.db import engine
from api.pc_configuration_copy import digest, explanation_digest
from api.part_explanations import is_current

PLAN = Path(__file__).parent / 'data' / 'pc_catalog_enrichment_20260930.json'


def validate_source(item, row):
    """Retailer automation requires reviewed evidence bound to an exact local model."""
    source = item['source']
    if source.get('kind') not in ('manufacturer', 'merchant') or not source.get('url', '').startswith('https://'):
        raise ValueError('Unsupported source')
    if source['kind'] == 'merchant':
        evidence = item.get('reviewed_evidence', {})
        if (row.get('product_code') != item['code'] or not is_current(row)
                or row.get('sale_status') != '판매중'
                or item.get('assembly_specs')
                or evidence.get('product_name') != row.get('product_name')
                or evidence.get('source_fingerprint') != row.get('source_fingerprint')
                or not evidence.get('locator') or not evidence.get('observed_at')
                or evidence.get('exact_model') is not True
                or evidence.get('conflict') is not False
                or evidence.get('version_sensitive') is not False):
            raise ValueError('Retailer model/evidence requires review')
    return '제조사 자료 대조' if source['kind'] == 'manufacturer' else '판매처 게시 사양 대조'


def apply(c, snapshot, plan):
    c.execute(text("SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))"))
    original_rows = {r['source_product_code']:r for r in snapshot['rows']}
    original_specs = {r['product_code']:r for r in snapshot['specs']}
    original_configs = {r['configuration_id']:r for r in snapshot['configs']}
    backups = dict(explanations=[], specs=[], products=[], configurations=[])
    touched = {}
    for item in plan:
        code = item['code']
        row = dict(c.execute(text('SELECT * FROM product_explanations WHERE source_product_code=:code FOR UPDATE'), dict(code=code)).mappings().one())
        assert row['status'] == 'draft' and explanation_digest(row) == explanation_digest(original_rows[code]), 'Explanation changed'
        validation_row = dict(original_rows[code], **row)
        verification = validate_source(item, validation_row)
        content = copy.deepcopy(row['content'])
        assert not any(s['id'] == item['source']['id'] for s in content['sources']), 'Source already applied'
        source = dict(item['source'], observed_at='2026-09-30')
        if item.get('reviewed_evidence'):
            source['reviewed_evidence'] = item['reviewed_evidence']
        if item.get('evidence_image'):
            source['evidence_image'] = item['evidence_image']
        content['sources'].append(source)
        labels = {f['label'] for f in content['facts']}
        for label, value in item['facts']:
            assert label not in labels, 'Do not overwrite existing facts'
            content['facts'].append(dict(label=label, value=value, source_id=source['id'], verification=verification))
        content.setdefault('cautions', []).append(item['note'])
        for route in item.get('issue_routes', []):
            assert route['issue'] in content.get('review_issues', []), 'Issue changed'
            assert route['source_fingerprint'] == row['source_fingerprint'] and is_current(validation_row), 'Issue source changed'
            assert route['stage'] == 'assembly' and route.get('reason') and route.get('source_url','').startswith('https://')
            assert not any(r['issue']==route['issue'] for r in content.get('review_issue_routes', [])), 'Issue already routed'
            content.setdefault('review_issue_routes', []).append(route)
        if item.get('assembly_specs'):
            assert row['product_code'] is None and content.get('availability_scope') == 'assembly_only'
            assert not content.get('review_specs'), 'Existing review facts must be reviewed separately'
            content['review_specs'] = dict(fields=item['assembly_specs'], source_id=source['id'],
                                          source_fingerprint=row['source_fingerprint'])
        if item.get('specs'):
            assert row['product_code'] == code
            prod = dict(c.execute(text('SELECT product_code,product_name,spec_source_text,locked_fields,status FROM products WHERE product_code=:code FOR UPDATE'),dict(code=code)).mappings().one())
            assert prod['product_name'] == original_rows[code]['product_name'] and prod['spec_source_text'] == original_rows[code]['spec_source_text'], 'Merchant source changed'
            assert prod['status'] == original_rows[code]['sale_status'] == '판매중', 'Sale status changed'
            spec = dict(c.execute(text('SELECT * FROM product_specs WHERE product_code=:code FOR UPDATE'),dict(code=code)).mappings().one())
            assert digest(spec) == digest(original_specs[code]), 'Spec changed'
            backups['specs'].append(spec)
            backups['products'].append(prod)
            sources = dict(spec.get('spec_sources') or {})
            for field, value in item['specs'].items():
                assert field in {'cooler_tdp','gpu_power_draw_watt'} and type(value) is int and value > 0
                assert spec[field] is None, 'Do not overwrite existing facts'
                assert field not in (prod['locked_fields'] or []) and 'specs.'+field not in (prod['locked_fields'] or []), 'Locked field requires review'
                c.execute(text(f'UPDATE product_specs SET {field}=:value WHERE product_code=:code'),dict(code=code,value=value))
                sources[field] = source['kind'] + ':2026-09-30:' + source['url']
            c.execute(text('UPDATE product_specs SET spec_sources=CAST(:v AS jsonb),updated_at=now() WHERE product_code=:code'),dict(code=code,v=json.dumps(sources)))
            # Automatic source values are not human-confirmed: never add them to locked_fields
            # (only the admin spec-entry path locks). The source is kept in spec_sources.
        backups['explanations'].append(row)
        content.setdefault('resolved_issues',[]).append(dict(date='2026-09-30', resolution=item.get('resolution',verification+' · 누락 사양 보완'), source_id=source['id']))
        c.execute(text('UPDATE product_explanations SET content=CAST(:v AS jsonb),updated_at=now() WHERE source_product_code=:code'),dict(code=code,v=json.dumps(content,ensure_ascii=False)))
        touched[code] = explanation_digest(dict(row,content=content))

    ids = c.execute(text('SELECT DISTINCT configuration_id FROM pc_configuration_parts WHERE explanation_code=ANY(:codes) ORDER BY configuration_id'),dict(codes=sorted(touched))).scalars().all()
    for identity in ids:
        cfg = dict(c.execute(text('SELECT * FROM pc_configurations WHERE configuration_id=:id FOR UPDATE'),dict(id=identity)).mappings().one())
        assert digest(cfg) == digest(original_configs[identity]), 'Configuration changed'
        parts = [dict(r) for r in c.execute(text('SELECT * FROM pc_configuration_parts WHERE configuration_id=:id ORDER BY ordinal'),dict(id=identity)).mappings()]
        offers = [dict(r) for r in c.execute(text('SELECT * FROM pc_configuration_offers WHERE configuration_id=:id ORDER BY offer_id'),dict(id=identity)).mappings()]
        snap = dict(cfg,parts=copy.deepcopy(parts),offers=offers,edit=dict(kind='source_enrichment',name='source-research-20260930',reason='출처별 사양 보완 및 설명 동기화; BOM·가격·상태 유지'))
        backups['configurations'].append(snap)
        c.execute(text('INSERT INTO pc_configuration_history(configuration_id,revision,snapshot) VALUES(:id,:rev,CAST(:v AS jsonb))'),dict(id=identity,rev=cfg['revision'],v=json.dumps(snap,ensure_ascii=False,default=str)))
        for p in parts:
            if p['explanation_code'] in touched:
                p['explanation_hash'] = touched[p['explanation_code']]
                c.execute(text('UPDATE pc_configuration_parts SET explanation_hash=:h WHERE configuration_id=:id AND ordinal=:n'),dict(id=identity,n=p['ordinal'],h=p['explanation_hash']))
        c.execute(text('UPDATE pc_configurations SET revision=revision+1,content_hash=:h,copy_hash=:ch,updated_at=now() WHERE configuration_id=:id'),dict(id=identity,h=digest(dict(content=cfg['content'],parts=parts,offers=offers)),ch=digest(dict(content=cfg['content'],parts=parts))))
    return dict(plan=plan,backups=backups,synced_configurations=ids)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--plan',type=Path,default=PLAN)
    p.add_argument('--apply',action='store_true')
    args = p.parse_args()
    out = Path(args.out)
    assert not out.exists(), 'New backup file required'
    out.parent.mkdir(parents=True,exist_ok=True)
    snapshot = json.loads(Path(args.source).read_text(encoding='utf-8'))
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    with engine.connect() as c:
        tx = c.begin()
        try:
            result = apply(c,snapshot,plan)
            result['applied'] = False
            out.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            if args.apply:
                tx.commit()
                result['applied'] = True
                out.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            else:
                tx.rollback()
        except Exception:
            if tx.is_active: tx.rollback()
            raise
    print(json.dumps(dict(applied=result['applied'],parts=len(plan),synced_configurations=len(result['synced_configurations'])),ensure_ascii=False))
