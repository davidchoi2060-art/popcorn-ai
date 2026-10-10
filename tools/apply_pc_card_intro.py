"""조립PC 카드의 소개 문장(intro)만 바꾸고, 같은 근거로 심사·고객 공개를 다시 승인한다.

소개 문장은 심사 근거값(basis)에 들어가므로, 문장만 바꿔도 카드가 고객 화면에서
내려간다(심사 '근거 변경' -> 공개 판정 거짓). 그래서 세 단계를 한 트랜잭션에서
순서대로 부른다. 모두 기존 API 계층 함수이고, 이 도구에는 직접 쓰는 SQL 이 없다(읽기 하나: 운영자 확인).

  1. 설명 수정     api.pc_configuration_edit.save_copy        (소개 한 항목만 바뀐다)
  2. 심사 승인     api.pc_configuration_review.save_review    (직전 승인의 확인 항목을 그대로 쓰고,
                                                              '설명 일치' 근거에만 문장 교체 사실을 적는다)
  3. 고객 공개     api.pc_customer_publication.approve         (고객 화면과 같은 사진 근거 판독기)

한 단계라도 실패하면 전부 되돌린다 -- 카드가 내려간 채로 남지 않는다.

손대지 않는 경우(이유를 출력하고 건너뛴다):
  - 지금 심사 승인 + 고객 공개 상태가 아닌 카드 (처음 승인은 이 도구의 일이 아니다)
  - 소개 외 다른 항목까지 바뀌게 되는 경우 (예: 기존 설명이 지금 형식 검사에 안 맞음)
  - 직전 승인에 없던 확인 항목이 새로 생긴 경우
  - 문장 근거 검사(claim_issues)에 걸리는 새 문장

문장 파일(JSON):
  {"cards": [{"product_code": 98149, "intro": "새 소개 문장"}, ...]}

기본은 미리보기다: 같은 순서를 실제로 실행해 본 뒤 ROLLBACK 한다(저장되는 것 없음).
바뀔 상품 · 전/후 문장 · 근거값 변화 · 공개 판정을 보여준다.
--apply 일 때만 COMMIT 하고, 커밋 뒤 고객 화면과 같은 경로로 다시 읽어 공개 여부를 출력한다.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NAMESPACE = UUID('5f0a7d3e-2c41-4b8e-9a6d-1e3c7b9f2a40')
DEFAULT_OPERATOR = 4
NOTE = '카드 소개 문장 교체 후 같은 근거로 재승인 (tools/apply_pc_card_intro.py)'
COPY_KEY = 'copy'


class Refuse(Exception):
    """이 카드는 이 도구로 바꾸지 않는다. 사유는 메시지에 쓴다."""


def rid(*parts):
    return str(uuid5(NAMESPACE, ':'.join(str(p) for p in parts)))


def short(value):
    return (value or '')[:12] + '…' if value else '없음'


def load_cards(path):
    """문장 파일을 읽어 {상품번호: 소개 문장}과 파일 지문을 돌려준다. 형식이 틀리면 ValueError."""
    raw = Path(path).read_bytes()
    data = json.loads(raw.decode('utf-8'))
    cards = data.get('cards') if isinstance(data, dict) else None
    if not isinstance(cards, list) or not cards:
        raise ValueError('"cards" 목록이 없습니다')
    found = {}
    for i, card in enumerate(cards):
        if not isinstance(card, dict) or set(card) - {'product_code', 'intro', 'note'}:
            raise ValueError(f'{i}번째 항목: product_code · intro (· note) 만 쓸 수 있습니다')
        code, intro = card.get('product_code'), card.get('intro')
        if type(code) is not int or code <= 0:
            raise ValueError(f'{i}번째 항목: product_code 는 양의 정수여야 합니다')
        if not isinstance(intro, str) or not intro.strip() or len(intro.strip()) > 3000:
            raise ValueError(f'{i}번째 항목({code}): intro 는 1~3000자 문장이어야 합니다')
        if code in found:
            raise ValueError(f'상품 {code} 가 두 번 들어 있습니다')
        found[code] = intro.strip()
    return found, hashlib.sha256(raw).hexdigest()


def file_ref(path):
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def load_actor(conn, operator_id):
    from sqlalchemy import text
    row = conn.execute(text('SELECT operator_id,name,role,status FROM admin_operators WHERE operator_id=:o'),
                       dict(o=operator_id)).mappings().first()
    if not row or row['role'] not in ('owner', 'operator') or row['status'] != '활성':
        raise Refuse(f'운영자 {operator_id} 는 활성 owner/operator 가 아닙니다')
    return dict(row)


def build_edit(config, intro, basis):
    """소개만 바꾼 설명 수정 요청. 다른 항목이 하나라도 달라지면 거부한다."""
    from pydantic import ValidationError
    from api.pc_configuration_edit import CopyEdit, EDITABLE
    prior = config['content']
    fields = {k: prior.get(k, {} if k == 'recommendation_policy' else [] if k in ('benefits', 'checks', 'faq') else '')
              for k in EDITABLE}
    fields['intro'] = intro
    try:
        body = CopyEdit(revision=config['revision'], content=fields, source_basis=basis)
    except ValidationError as error:
        problems = ', '.join('.'.join(str(p) for p in e['loc'][1:]) or e['msg'] for e in error.errors())
        raise Refuse(f'기존 설명이 지금 형식 검사에 맞지 않아 소개만 바꿀 수 없습니다: {problems}')
    dumped = body.content.model_dump(mode='json')
    changed = [k for k in EDITABLE if dumped[k] != prior.get(k)]
    if changed != ['intro']:
        raise Refuse('소개 외 다른 항목도 바뀌게 됩니다: ' + ', '.join(k for k in changed if k != 'intro'))
    return body


def reuse_findings(saved, required, evidence_note):
    """직전 승인의 확인 항목을 그대로 쓴다. '설명 일치'만 문장 교체 근거를 앞에 붙인다."""
    from api.pc_configuration_review import Finding
    prior = saved.get('findings') or {}
    findings = {}
    for key, label in required.items():
        f = prior.get(key) or {}
        if f.get('confirmed') is not True or len((f.get('evidence') or '').strip()) < 10:
            raise Refuse(f'직전 승인에 없던 확인 항목이 있습니다: {label}')
        evidence = f['evidence'].strip()
        if key == COPY_KEY:
            evidence = (evidence_note + ' / 이전 근거: ' + evidence)[:2000]
        findings[key] = Finding(confirmed=True, evidence=evidence)
    return findings


def make_reader():
    from api.customer_pc_offer import cached_read_image, rights_reference
    from api.pc_publication_source_reader import make_source_reader
    rights = rights_reference()
    if not rights:
        raise Refuse('부품 사진 권리 참조값을 읽지 못했습니다(고객 화면도 같은 이유로 닫힘)')
    return make_source_reader(image_reader=cached_read_image, business_rights_reference=rights)


def change_one(conn, code, intro, operator_id, reader, source):
    """한 트랜잭션 안에서 세 단계를 부른다. 커밋/롤백은 부른 쪽이 한다."""
    from api import pc_customer_publication as publication
    from api.pc_configuration_copy import read_sold_offer_configuration
    from api.pc_configuration_edit import save_copy
    from api.pc_configuration_review import ReviewEdit, load_review, save_review

    actor = load_actor(conn, operator_id)
    identity = read_sold_offer_configuration(conn, code)['configuration_id']
    config, _, _, state = load_review(conn, identity)
    before = publication.read_current(conn, identity, source_reader=reader)
    row = dict(product_code=code, configuration_id=identity, revision_before=config['revision'],
               intro_before=config['content'].get('intro'), intro_after=intro,
               review_basis_before=state['basis'], publication_basis_before=before['publication_basis'])
    if state['state'] != 'approved' or state['eligible'] is not True:
        raise Refuse(f"지금 심사 승인 상태가 아닙니다({state['state']}) -- 처음 승인은 이 도구로 하지 않습니다")
    if before['allowed'] is not True:
        raise Refuse(f"지금 고객 공개 상태가 아닙니다({before['state']} · {before['reason']})")
    if row['intro_before'] == intro:
        return dict(row, outcome='unchanged')
    saved = config['content'].get('_review') or {}

    save_copy(conn, identity, build_edit(config, intro, state['basis']), actor)

    _, _, _, mid = load_review(conn, identity)
    if mid['blockers']:
        raise Refuse('소개를 바꾼 뒤 심사 보완 항목이 생겼습니다: ' + ' / '.join(mid['blockers']))
    note = f'카드 소개 문장만 교체: {source}#{code}. 제목·혜택·구성·가격·부품 그대로'
    save_review(conn, identity, ReviewEdit(revision=mid['revision'], basis=mid['basis'], action='approve',
                                           findings=reuse_findings(saved, mid['required'], note), note=NOTE), actor)

    cur = publication.read_current(conn, identity, source_reader=reader)
    if cur['publication_basis'] is None:
        raise Refuse(f"공개 근거를 다시 만들지 못했습니다({cur['reason']})")
    publication.approve(conn, identity, expected_seq=cur['event_seq'], revision=cur['revision'],
                        review_basis=cur['basis'], publication_basis=cur['publication_basis'],
                        request_id=rid('card-intro', identity, cur['publication_basis']),
                        note=NOTE, actor=actor, source_reader=reader)
    after = publication.read_current(conn, identity, source_reader=reader)
    if after['allowed'] is not True:
        raise Refuse(f"공개 승인 뒤에도 공개 판정이 거짓입니다({after['state']} · {after['reason']})")
    return dict(row, outcome='changed', revision_after=after['revision'], review_basis_after=after['basis'],
                publication_basis_after=after['publication_basis'], publication_allowed=after['allowed'])


def run_one(engine, code, intro, *, apply, operator_id, source, reader_factory=make_reader):
    from fastapi import HTTPException
    conn = engine.connect().execution_options(isolation_level='REPEATABLE READ')
    try:
        tx = conn.begin()
        try:
            row = change_one(conn, code, intro, operator_id, reader_factory(), source)
        except Refuse as error:
            tx.rollback()
            return dict(product_code=code, outcome='refused', reason=str(error))
        except HTTPException as error:
            tx.rollback()
            return dict(product_code=code, outcome='refused', reason=f'{error.status_code} {error.detail}')
        except Exception:
            tx.rollback()
            raise
        if apply and row['outcome'] == 'changed':
            tx.commit()
            row['committed'] = True
        else:
            tx.rollback()
            row['committed'] = False
        return row
    finally:
        conn.close()


def customer_view(code):
    """고객 화면과 같은 경로(읽기 전용 스냅샷)로 다시 읽는다."""
    from api.customer_pc_offer import public_item
    public = (public_item(code) or {}).get('public_configuration')
    if not public:
        return False, None
    return True, (public.get('description') or {}).get('intro')


def report(row, out=print):
    code = row['product_code']
    if row['outcome'] == 'refused':
        out(f'상품 {code} · 건너뜀: {row["reason"]}')
        return
    out(f"상품 {code} · 구성 {row['configuration_id']} · 수정번호 {row['revision_before']}")
    out(f"  바뀌기 전 소개: {row['intro_before']}")
    out(f"  바뀐 뒤 소개:   {row['intro_after']}")
    if row['outcome'] == 'unchanged':
        out('  결과: 이미 같은 문장입니다 -- 바꾸지 않았습니다')
        return
    out(f"  심사 근거값: {short(row['review_basis_before'])} -> {short(row['review_basis_after'])}")
    out(f"  공개 근거값: {short(row['publication_basis_before'])} -> {short(row['publication_basis_after'])}")
    out(f"  공개 판정(같은 트랜잭션 안): {'참' if row['publication_allowed'] else '거짓'}")
    out('  결과: ' + ('반영했습니다(커밋)' if row['committed'] else '미리보기 -- 실행해 본 뒤 되돌렸습니다(저장 안 됨)'))


def main(argv=None, out=print):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--file', required=True, type=Path, help='새 소개 문장 JSON 파일')
    parser.add_argument('--product', required=True, type=int, action='append', help='바꿀 상품번호(반복 가능)')
    parser.add_argument('--operator-id', type=int, default=DEFAULT_OPERATOR, help=f'작업 운영자 번호(기본 {DEFAULT_OPERATOR})')
    parser.add_argument('--apply', action='store_true', help='실제 반영(기본은 미리보기)')
    args = parser.parse_args(argv)
    try:
        cards, digest = load_cards(args.file)
    except (OSError, ValueError) as error:
        parser.error(f'문장 파일 {args.file}: {error}')
    missing = [c for c in args.product if c not in cards]
    if missing:
        parser.error('문장 파일에 없는 상품번호: ' + ', '.join(map(str, missing)))
    source = f'{file_ref(args.file)}@sha256:{digest[:12]}'
    from api.db import engine
    out(('반영' if args.apply else '미리보기') + f' · 운영자 {args.operator_id} · 문장 파일 {source}')
    failed = 0
    for code in dict.fromkeys(args.product):
        row = run_one(engine, code, cards[code], apply=args.apply, operator_id=args.operator_id, source=source)
        report(row, out)
        if row['outcome'] == 'refused':
            failed += 1
            continue
        public, intro = customer_view(code)
        shown = '새 문장' if intro == cards[code] else '이전 문장' if intro == row['intro_before'] else '다른 문장'
        out(f"  고객 화면 공개(지금 다시 읽음): {'예' if public else '아니오'}" + (f' · 보이는 소개: {shown}' if public else ''))
        if row.get('committed') and (not public or intro != cards[code]):
            failed += 1
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
