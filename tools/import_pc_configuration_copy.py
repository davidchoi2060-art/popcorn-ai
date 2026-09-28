"""Dry-run-first catalog import. Snapshot prices, immutable part identities, no quote generation."""
import argparse,hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from api.db import engine
from api.pc_configuration_copy import digest,explanation_digest

COPY_KEYS=('title','intro','benefits','scene','question','checks','category','facts','specs','appearance','variant_label','faq','evidence','recommendation_policy','similar_build','source','source_ids')

def prepare(records, explanations):
    result=[];ids=set();boms=set();offers=set()
    for r in records:
        assert r['id'] not in ids and r['bom_fingerprint'] not in boms,'Duplicate configuration/BOM'
        ids.add(r['id']);boms.add(r['bom_fingerprint'])
        for k in ('title','intro','benefits','scene','question','checks','faq'):assert r.get(k),f'Missing copy {r["id"]}: {k}'
        signature=tuple(sorted((p['slot'],p['code'],p['quantity']) for p in r['parts'] if not(p['slot']=='GPU' and p['pseudo'])))
        assert hashlib.sha256(json.dumps(signature).encode()).hexdigest()==r['bom_fingerprint'],'BOM hash mismatch'
        parts=[]
        for i,p in enumerate(r['parts']):
            assert isinstance(p['quantity'],int) and p['quantity']>0
            code=None if p['pseudo'] else int(p['code'])
            assert p['pseudo'] or code in explanations,f'Missing component explanation: {code}'
            parts.append(dict(ordinal=i,slot=p['slot'],source_code=p['code'],explanation_code=code,quantity=p['quantity'],pseudo=p['pseudo'],selection_note=p.get('selection_note',p['role']),explanation_hash=None if p['pseudo'] else explanation_digest(explanations[code])))
        for o in r['offers']:
            assert o['id'] not in offers,'Offer assigned to multiple BOMs'
            offers.add(o['id'])
            assert isinstance(o['price'],int) and o['price']>0
            assert o['price']==o['base_price']+o['assembly_fee_added'],'Assembly fee mismatch'
            assert o['assembly_fee_added']==(30000 if o['id'].startswith('N') else 0),'Assembly fee duplicated or omitted'
        payload=dict(content={k:r[k] for k in COPY_KEYS},parts=parts,offers=r['offers'],observed_date=r['observed_date'],bom_fingerprint=r['bom_fingerprint'])
        copy_basis=dict(content={k:v for k,v in payload['content'].items() if k!='evidence'},parts=parts,bom_fingerprint=r['bom_fingerprint'])
        result.append(dict(id=r['id'],hash=digest(payload),copy_hash=digest(copy_basis),**payload))
    return result

def apply_rows(c,prepared,replace=False):
    # Every writer through this tool shares one transaction-scoped catalog lock.
    c.execute(text("SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))"))
    changes=[]
    for item in prepared:
        prior=c.execute(text('SELECT * FROM pc_configurations WHERE configuration_id=:id FOR UPDATE'),{'id':item['id']}).mappings().first()
        if prior and prior['content_hash']==item['hash']:continue
        assert not prior or replace,'Existing changed copy requires --replace; dry-run first'
        if prior:
            snapshot=dict(prior)
            for key,table in [('parts','pc_configuration_parts'),('offers','pc_configuration_offers')]:
                snapshot[key]=[dict(r) for r in c.execute(text(f'SELECT * FROM {table} WHERE configuration_id=:id'),{'id':item['id']}).mappings()]
            c.execute(text('INSERT INTO pc_configuration_history(configuration_id,revision,snapshot) VALUES(:id,:revision,CAST(:snapshot AS jsonb))'),{'id':item['id'],'revision':prior['revision'],'snapshot':json.dumps(snapshot,ensure_ascii=False,default=str)})
        c.execute(text('''INSERT INTO pc_configurations(configuration_id,bom_fingerprint,content,content_hash,copy_hash,observed_date)
          VALUES(:id,:bom,CAST(:content AS jsonb),:hash,:copy_hash,:date)
          ON CONFLICT(configuration_id) DO UPDATE SET bom_fingerprint=EXCLUDED.bom_fingerprint,
          content=EXCLUDED.content,content_hash=EXCLUDED.content_hash,observed_date=EXCLUDED.observed_date,
          revision=pc_configurations.revision+1,
          status=CASE WHEN pc_configurations.copy_hash<>EXCLUDED.copy_hash THEN 'review_required' ELSE pc_configurations.status END,
          copy_hash=EXCLUDED.copy_hash,updated_at=now()'''),
          {'id':item['id'],'bom':item['bom_fingerprint'],'content':json.dumps(item['content'],ensure_ascii=False),'hash':item['hash'],'copy_hash':item['copy_hash'],'date':item['observed_date']})
        for table in ['pc_configuration_parts','pc_configuration_offers']:
            c.execute(text(f'DELETE FROM {table} WHERE configuration_id=:id'),{'id':item['id']})
        for p in item['parts']:
            c.execute(text('''INSERT INTO pc_configuration_parts(configuration_id,ordinal,slot,source_code,explanation_code,quantity,pseudo,selection_note,explanation_hash)
              VALUES(:id,:ordinal,:slot,:source_code,:explanation_code,:quantity,:pseudo,:selection_note,:explanation_hash)'''),dict(id=item['id'],**p))
        for o in item['offers']:
            c.execute(text('INSERT INTO pc_configuration_offers(offer_id,configuration_id,price_snapshot,payload) VALUES(:offer,:id,:price,CAST(:payload AS jsonb))'),{'offer':o['id'],'id':item['id'],'price':o['price'],'payload':json.dumps(o,ensure_ascii=False)})
        changes.append(item['id'])
    return changes

def main():
    p=argparse.ArgumentParser();p.add_argument('catalog',type=Path);p.add_argument('--parts',type=Path,required=True);p.add_argument('--apply',action='store_true');p.add_argument('--replace',action='store_true');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    catalog=json.loads(a.catalog.read_text(encoding='utf-8'))
    export={int(r['product_code']):r for r in json.loads(a.parts.read_text(encoding='utf-8'))}
    parts_hash=hashlib.sha256(a.parts.read_bytes()).hexdigest()
    assert all(r['evidence']['parts_sha256']==parts_hash for r in catalog['records']),'Catalog was built against different part explanations'
    a.output.mkdir(parents=True,exist_ok=True)
    with engine.begin() as c:
        explanations={r['source_product_code']:dict(r) for r in c.execute(text('SELECT * FROM product_explanations FOR SHARE')).mappings()}
        for code,p in export.items():
            for k in ['facts','role','review_issues']:assert p[k]==explanations[code]['content'][k],f'Part changed after export: {code}/{k}'
        prepared=prepare(catalog['records'],explanations)
        exists=c.execute(text("SELECT to_regclass('public.pc_configurations')")).scalar()
        before={}
        if exists:
            for table in ['pc_configurations','pc_configuration_parts','pc_configuration_offers','pc_configuration_history']:
                before[table]=[dict(r) for r in c.execute(text(f'SELECT * FROM {table}')).mappings()]
        known={r['configuration_id']:r['content_hash'] for r in before.get('pc_configurations',[])}
        result=dict(configurations=len(prepared),offers=sum(len(i['offers']) for i in prepared),part_links=sum(len(i['parts']) for i in prepared),real_component_codes=len({p['explanation_code'] for i in prepared for p in i['parts'] if not p['pseudo']}),new=sum(i['id'] not in known for i in prepared),changed=sum(i['id'] in known and known[i['id']]!=i['hash'] for i in prepared),applied=False)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        if a.apply:
            assert exists,'Run additive migration 0117 before applying'
            backup=a.output/f'catalog-before-{stamp}.json'
            backup.write_text(json.dumps(before,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            changed=apply_rows(c,prepared,a.replace)
            for i in prepared:
                assert c.execute(text('SELECT content_hash FROM pc_configurations WHERE configuration_id=:id'),{'id':i['id']}).scalar_one()==i['hash']
            result.update(applied=True,written=len(changed),backup=backup.name)
        # This report is written only after the transaction exits successfully below.
    (a.output/f'catalog-import-{stamp}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
