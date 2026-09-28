"""Partial-spec comparison rules promoted from the reviewed local pilot. Not performance guarantees."""
import re

LABELS = {'ram_gb':'RAM(GB)','storage_gb':'총 SSD 용량(GB)','vram_gb':'전용 GPU 메모리(GB)',
          'cores':'물리 코어 수','threads':'논리 스레드 수','base_ghz':'기본 클럭(GHz)','boost_ghz':'최대 클럭(GHz)'}

def number(text, summed=False):
    if not text: return None
    found=re.findall(r'\d+(?:\.\d+)?', str(text))
    if not found: return None
    return sum(float(n) for n in found) if summed else float(found[0])

def facts_for(pc):
    f=dict(pc['facts'])
    cpu=next((p for p in pc['parts'] if p['slot']=='CPU'),{})
    fields={x['label']:x['value'] for x in cpu.get('facts',[])}
    for key,label in [('cores','코어 구성'),('threads','스레드'),('base_ghz','기본 클럭'),('boost_ghz','최대 클럭')]:
        f[key]=number(fields.get(label),key in ('cores','threads'))
    f['storage_devices']=sum(p['quantity'] for p in pc['parts'] if p['slot'] in ('SSD','HDD') and not p['pseudo'])
    return f

def check(key, needed, actual, basis):
    state='unknown' if actual is None else ('pass' if actual>=needed else 'fail')
    return dict(field=key,label=LABELS.get(key,key),required=needed,actual=actual,state=state,basis=basis)

def overall(checks):
    if any(c['state']=='fail' for c in checks): return 'fail'
    if not checks or any(c['state']=='unknown' for c in checks): return 'unknown'
    return 'pass'

def evaluate(pc,s,requirements):
    f=facts_for(pc); minimum=[]; recommended=[]; unknown=[]
    for app in s['apps']:
        req=requirements.get(app)
        if not req: continue
        for target,dest in [('min',minimum),('rec',recommended)]:
            for k,n in req[target].items():
                dest.append(check(k,n,f.get(k),app))
        unknown.extend(req['unknown'])
        if app in ('premiere','aftereffects'):
            recommended.append(check('ram_gb',32 if s['media_level']=='4K' else 16,f['ram_gb'],app))
            # A single device does not satisfy the supplied PC's additional media-drive requirement.
            drive=check('storage_devices',2,f['storage_devices'],app)
            drive['label']='本体 내 물리 저장장치 수'.replace('本体','본체')
            drive['note']='이미 가진 외장/NAS 미디어 드라이브를 연결할 수 있지만 현재 본체 구성에는 포함되지 않음'
            minimum.append(drive); recommended.append(dict(drive))
            if f['cpu'].startswith('Core') and f['cpu'].endswith('F'):
                recommended.append(dict(field='quick_sync',label='Intel 권장 Quick Sync 조건',state='fail',required=True,actual=False,basis=app,note='F/KF CPU는 내장 그래픽 없음. 외장 GPU 가속 가능 여부와 별개의 권장 조건'))
        if app=='photoshop':
            recommended.append(dict(field='scratch_drive',label='별도 스크래치 드라이브',required=2,actual=f['storage_devices'],state='pass' if f['storage_devices']>=2 else 'fail',basis=app))
    if s.get('monitors',1)>1: unknown.append(f"모니터 {s['monitors']}대 동시 출력·해상도·주사율·단자·케이블")
    if s.get('target_fps'): unknown.append(f"{s['resolution']} {s['target_fps']}FPS 목표 실측")
    if s.get('cycles'): unknown.append('Cycles CUDA/OptiX/HIP 백엔드·드라이버·장면 VRAM 실제 적재')
    policy={}
    for level in ('basic','better'):
        policy[level]=[check(k,v,f.get(k),'popcorn_policy_draft') for k,v in s[level].items()]
    # Only a subset can be checked; do not convert component capacities into overall run/performance claims.
    return dict(pc_id=pc['id'],bom_fingerprint=pc['bom_fingerprint'],scenario_id=s['id'],
      minimum_checks=minimum,recommended_checks=recommended,policy=policy,
      minimum_subset=overall(minimum),recommended_subset=overall(recommended),
      missing_checks=list(dict.fromkeys(unknown)),
      minimum_overall='fail' if overall(minimum)=='fail' else 'unknown',
      recommended_overall='fail' if overall(recommended)=='fail' else 'unknown',
      target_performance='unmeasured',customer_publishable=False)

def choose(pc_list, evaluations, s, level):
    options=[]
    for pc,e in zip(pc_list,evaluations):
        # Exclude every known minimum failure, including missing physical media drives.
        hard_fails=[c for c in e['minimum_checks'] if c['state']=='fail']
        if hard_fails or overall(e['policy'][level])!='pass': continue
        # Dedicated RAM is unknown on UMA. Keep these as unknown evaluations, not GPU-capacity-qualified cards.
        if any(c['field']=='vram_gb' and c['state']=='unknown' for c in e['minimum_checks']): continue
        if s.get('needs_model'): continue  # model-specific memory demand is essential before price selection
        offer=min(pc['offers'],key=lambda o:(o['price'],o['id']))
        options.append(dict(pc_id=pc['id'],offer_id=offer['id'],price=offer['price'],
          price_note=offer['price_note'],minimum_gaps=[c['label'] for c in e['minimum_checks'] if c['state']=='fail']))
    return sorted(options,key=lambda x:(x['price'],x['pc_id']))
