"""업무형 「회의록 정리」·「고객 답변 초안」 -> 각자의 업무 예시·구축 과정 설명 -> 그 업무로 도입 상담 (2026-10-21 대표 승인).

승인 원문: 「회의록 정리랑 고객답변 초안을 누르면 각각 업무 예시와 우리 회사에 맞게 구축하는 과정을 먼저 보여주고
상담으로 이어지게 해줘. 기존 헤더랑 메뉴는 그대로 두고.」
정본 business-meeting-guide.html SHA256 c4441a57…bd821 · business-reply-guide.html SHA256 052fc4cc…9a9878.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "mockups/mvp4"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def code(rel):
    """머리 주석을 뺀 실행 코드."""
    s = read(rel)
    return s[s.index("(function () {"):]


MEETING, REPLY = "assets/js/ai-meeting-guide.js", "assets/js/ai-reply-guide.js"


def test_four_detail_entries_and_home_go_to_their_own_explanation():
    s = read("assets/js/ai.js")
    assert "'ai-service.html?package=business&amp;use=' + u.id" in s and "SERVICE_USES[u.id]" in s
    detail = s[s.index("P.pages['ai-detail']"):s.index("P.pages['ai-consult']")]
    assert detail.count("uses(p,true)") == 1 and detail.count("uses(p,false)") == 1   # 상단 타일 + 아래 활용 카드
    home = read("assets/js/design-home.js")
    assert "/^(documents|meetings|replies)$/.test(f[2])" in home
    assert "'회의록 정리','meetings'" in home and "'고객 답변 초안','replies'" in home


def test_service_page_routes_by_use_and_loads_both_guides():
    html = read("ai-service.html")
    for asset in ("ai-meeting-guide.js?v=20261021-mm3", "ai-reply-guide.js?v=20261021-mm3",
                  "ai-meeting-guide.css?v=20261021-mm3", "ai-reply-guide.css?v=20261021-mm3", "header-ui.js?v=20261029-cat1"):
        assert asset in html, asset
    assert "P.serviceGuides.meetings = {label: '회의록 정리'" in read(MEETING)
    assert "P.serviceGuides.replies = {label: '고객 답변 초안'" in read(REPLY)


def test_guides_have_no_widget_host_network_or_storage():
    for rel in (MEETING, REPLY):
        js = code(rel)
        for bad in ("window.openai", "setWidgetState", "fetch(", "XMLHttpRequest", "localStorage",
                    "data-lucide", "미리보기", "시안", "history.", "<form", ".submit(", "type=\"submit\""):
            assert bad not in js, (rel, bad)


def test_consult_links_carry_each_use_with_adoption_intent():
    m, r = code(MEETING), code(REPLY)
    assert 'id="mg-consult-link" href="ai-consult.html?package=business&amp;use=meetings&amp;intent=adoption"' in m
    assert 'id="rp-consult-link" href="ai-consult.html?package=business&amp;use=replies&amp;intent=adoption"' in r
    assert "use=documents" not in m and "use=documents" not in r
    for js in (m, r):
        assert "이 화면을 본 것만으로 상담이 접수되거나 연락 동의가 되지 않습니다." in js
        assert 'href="ai-detail.html?package=business"' in js
    s = read("assets/js/ai-inquiry.js")
    assert "use:company ? '' : (P.qs.get('use') || '')" in s and "if(['quote','adoption'].indexOf(intent)<0)" in s


def test_meeting_example_keeps_counts_evidence_and_undecided_items():
    js = read(MEETING)
    assert len(re.findall(r'data-mg-utterance="u\d"', js)) == 8
    assert len(re.findall(r"\{id:'d\d'", js)) == 3 and len(re.findall(r"\{id:'t\d'", js)) == 2 and len(re.findall(r"\{id:'p\d'", js)) == 2
    assert "owner:'인사 담당',due:'10월 26일까지',refs:['u4']" in js
    assert "owner:'IT 담당',due:'10월 27일 오후 3시까지',refs:['u5']" in js
    # 사진 담당 의사·수요일 희망은 담당·기한을 받지 않는다(미정으로 남는다)
    pending = js[js.index("pending:["):js.index("var steps")]
    assert "owner:" not in pending and "due:" not in pending
    assert "“맡을 수 있을 것 같아요”를 확정 배정으로 바꾸지 않습니다." in js and "수요일을 확정 일정으로 등록하지 않는 예시입니다." in js
    for t in ("회의 내용 입력", "사내 AI 정리", "사람이 검토", "사내 공유", "우리 회사 회의록으로 구축하는 과정",
              "회의 유형·기존 양식 확인", "사용 안내·인계", "가상 예시", "외부 AI API를 사용하는 구성에는 ‘업무 데이터 외부 전송 없음’을 약속할 수 없습니다."):
        assert t in js, t
    assert "id=\"mg-document-button\" aria-expanded=\"false\" aria-controls=\"mg-document\"" in js
    css = read("assets/css/ai-meeting-guide.css")
    assert "#pop-meeting-guide .mg-flow{grid-template-columns:1fr" in css and "content:'↓'" in css   # 모바일 세로 화살표
    rules = css[css.index("*/") + 2:]
    assert "light-dark" not in rules and "Pretendard" not in rules


def test_reply_cases_sources_tone_copy_and_review_reset():
    js = read(REPLY)
    assert "setup:{title:" in js and "trouble:{title:" in js
    for doc in ("도입 안내 v2 · 2026-10-01 · §2", "설치 일정 안내 v1 · 2026-10-02 · §3", "자료 취급 안내 v2 · 2026-10-04 · §1",
                "지원 접수 안내 v3 · 2026-10-02 · §1", "자료 갱신 안내 v2 · 2026-10-03 · §2", "지원 처리 안내 v1 · 2026-10-05 · §4"):
        assert doc in js, doc
    assert "drafts:{detail:[" in js and "brief:[" in js and 'data-tone="detail"' in js and 'data-tone="brief"' in js
    for t in ("사내 자료에서 확인", "아직 확인이 필요한 것", "다음 주 금요일 설치는 아직 확정되지 않았으며", "오늘 오전까지 복구 가능한지는 아직 확정할 수 없습니다.",
              "문서 원본이나 비밀번호는 보내지 않으셔도 됩니다.", "자료와 적용 버전", "답변 범위와 확인 담당", "접근·보관·발송 절차",
              "업무 확인", "구성·범위 합의", "회사 기준 적용", "예외까지 검수", "사용 안내·인계", "모두 가상 예시입니다"):
        assert t in js, t
    m = code(REPLY)
    copy = m[m.index("function copyDraft()"):m.index("root.addEventListener('click'")]
    assert "q('#rp-draft').innerText" in copy                         # 지금 보이는 사례·말투 초안만
    ok = copy.index("navigator.clipboard.writeText(text).then(")
    assert copy.index("가상 예시 초안을 복사했습니다.") > ok            # 성공 응답 뒤에만 완료 표시
    assert "box.select()" in copy and "직접 복사해 주세요" in copy
    click = m[m.index("root.addEventListener('click'"):]
    assert "selected = b.dataset.case; source = 0; resetReview();" in click
    assert "tone = b.dataset.tone === 'brief' ? 'brief' : 'detail'; resetReview();" in click
    assert "checked = [];" in m[m.index("function resetReview()"):]
    assert "모두 선택해도 실제 승인·발송되지는 않습니다." in m


def test_design_only_labels_removed_and_virtual_labels_kept():
    for rel in (MEETING, REPLY):
        js = read(rel)
        body = js[js.index("var MARKUP"):]
        assert "디자인 시안" not in body and "상담 미리보기" not in body and "상담 연결 미리보기" not in body
        assert "가상" in body


# 2026-10-21 상단 미니어처(회의록 승인 3번 · 문서 검색·고객 답변 승인 시안): 그림은 각 hero 안에만, 장식(alt="")으로, 치수를 잡아 넣는다.
def test_hero_miniatures_are_scoped_decorative_and_sized():
    import hashlib
    img = ROOT / "assets/images/business"
    assert hashlib.sha256((img / "meeting-miniature.png").read_bytes()).hexdigest() == "b858e136730510a2c9a8eb1532ed5a5301f7a72468a781de7f0da5c2fc4b9418"
    for rel, name, wh, scope in ((MEETING, "meeting-miniature.png", 'width="2048" height="768"', "#pop-meeting-guide"),
                                 ("assets/js/ai-local-service.js", "documents-miniature.png", 'width="998" height="470"', "#pop-local-service"),
                                 (REPLY, "replies-miniature.png", 'width="984" height="418"', "#pop-reply-guide")):
        js = read(rel)
        assert js.count(name) == 1 and wh in js and 'aria-hidden="true"><img' in js and 'alt=""' in js, rel
        assert (img / name).exists(), name
    for css, scope in (("assets/css/ai-meeting-guide.css", "#pop-meeting-guide"), ("assets/css/ai-local-service.css", "#pop-local-service"), ("assets/css/ai-reply-guide.css", "#pop-reply-guide")):
        src = read(css); assert "상단 미니어처" in src, css
        tail = src[src.index("상단 미니어처"):]; tail = tail[tail.index("*/") + 2:]
        rules = [r.split("{")[0].strip() for r in tail.replace("@media(max-width:1023px){", "").split("}") if "{" in r and not r.strip().startswith("/*")]
        assert rules and all(r.startswith(scope) for r in rules if r), (css, rules)
