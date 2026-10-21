"""업무형 「사내 문서 검색」 -> 회사 맞춤 내부 AI 구축 설명 -> 도입 상담 (2026-10-21 대표 승인).

승인 원문: 「사내문서 검색을 누르면 업무 예시랑 우리 회사에 맞게 구축해주는 과정을 먼저 보여주고, 그다음 상담으로
이어지게 해줘. 기존 헤더랑 메뉴는 그대로 두고.」 정본 business-local-ai-service.html SHA256 772629e8….
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "mockups/mvp4"
JS = ROOT / "assets/js"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def code(rel):
    """머리 주석을 뺀 실행 코드."""
    s = read(rel)
    return s[s.index("(function () {"):]


def test_business_use_entries_go_to_their_explanation():
    s = read("assets/js/ai.js")
    # 2026-10-21 회의록 정리·고객 답변 초안 승인으로 업무형 세 업무가 각자의 설명 화면으로 간다(test_business_meeting_reply_guides_20261021)
    assert "var SERVICE_USES = {documents: 1, meetings: 1, replies: 1};" in s
    assert "p.id === 'business' && SERVICE_USES[u.id] ? 'ai-service.html?package=business&amp;use=' + u.id" in s
    assert "useHref(p, u)" in s and "link('ai-consult', {package:p.id, use:u.id})" in s     # 다른 업무·패키지는 기존 상담 그대로
    # 상단 타일과 아래 활용 카드가 같은 uses() 를 쓴다
    detail = s[s.index("P.pages['ai-detail']"):s.index("P.pages['ai-consult']")]
    assert detail.count("uses(p,true)") == 1 and detail.count("uses(p,false)") == 1


def test_explanation_page_uses_site_shell_and_its_own_body_only():
    html = read("ai-service.html")
    assert 'data-page="ai-service"' in html and "boot.js" in html and "header-ui.js?v=20261020-logo2" in html
    assert "ai-local-service.js?v=20261021-mr1" in html and "ai-local-service.css?v=20261021-svc1" in html
    js = code("assets/js/ai-local-service.js")
    assert "window.openai" not in js and "setWidgetState" not in js and "fetch(" not in js and "localStorage" not in js
    assert "P.serviceGuides.documents = {label: '사내 문서 검색', body: body, mount: mount};" in js
    assert "P.qs.get('package') === 'business' && Object.prototype.hasOwnProperty.call(P.serviceGuides, use)" in js


def test_approved_content_is_kept():
    js = read("assets/js/ai-local-service.js")
    for text in ("회사 자료는 회사 안에.<br>AI는 우리 업무에 맞게.", "내부 전용 목표 구성", "외부 API 연결 구성과 비교",
                 "밖에서 들어오지 못하도록", "안의 업무 내용이 나가지 않도록", "ChatGPT와 무엇이 다른가요?",
                 "‘학습에 사용하지 않음’과 ‘외부로 전송하지 않음’은 다른 조건입니다.",
                 "https://learn.chatgpt.com/docs/use-chatgpt", "현재 안내하는 상담 범위", "회사별 제공 가능 여부·범위 확정",
                 "업무 진단", "설계·견적", "설치·구성", "실무 검수", "안내·인계",
                 "사내 규정 확인", "영업 제안 준비", "고객 안내 작성", "모두 가상 예시입니다",
                 "업데이트·원격지원·백업·진단 기능에 외부 연결이 있는지",
                 "이 구성에는 ‘업무 데이터 외부 전송 없음’을 적용할 수 없습니다.",
                 "내부 전용은 구축·통신 검증 후 확정하는 목표 구성입니다.", "운영 사이트의 보안 검증 완료나 고객 설치 완료를 뜻하지 않습니다.",
                 "‘사내 AI’라는 이유로 답변이 항상 정확하다고 보장하지 않습니다."):
        assert text in js, text
    assert len(re.findall(r"data-stage=\"\d\"", js)) == 5 and len(re.findall(r"data-case=\"\w+\"", js)) == 3


def test_preview_became_real_consult_link_without_submitting_anything():
    js = code("assets/js/ai-local-service.js")
    assert 'href="ai-consult.html?package=business&amp;use=documents&amp;intent=adoption"' in js
    assert "우리 회사 내부 AI 구축 상담하기" in js
    assert "미리보기" not in js and "화면 제안 ·" not in js and "data-lucide" not in js
    assert "이 화면을 본 것만으로 상담이 접수되거나 연락 동의가 되지 않습니다." in js
    # 비교 탭은 화면만 바꾼다 -- 상담 링크를 고치는 코드가 없다
    handler = js[js.index("function mount()"):]
    assert "ls-consult-link" not in handler and "history." not in handler


def test_consult_form_preselects_use_from_url_and_skips_gate_for_adoption():
    s = read("assets/js/ai-inquiry.js")
    assert "use:P.qs.get('use') || ''" in s
    assert "if(['quote','adoption'].indexOf(intent)<0)" in s       # 목적 재선택은 intent 가 없을 때만


def test_ai_pages_load_new_ai_js():
    for page in ("ai-detail.html", "ai-consult.html", "ai-packages.html", "ai-result.html", "ai-service.html"):
        assert "ai.js?v=20261021-mr1" in read(page), page


def test_home_business_card_documents_also_goes_to_the_explanation():
    """홈 업무형 카드의 사내 문서 검색도 같은 설명 화면으로 (승인 원문 「사내문서 검색을 누르면 … 먼저 보여주고」)."""
    s = read("assets/js/design-home.js")
    assert "(/^(documents|meetings|replies)$/.test(f[2]) ? 'ai-service.html?package=business&amp;use=' + f[2] : 'ai-consult.html?package=business&amp;use=' + f[2])" in s
    for page in ("index.html", "review-flows.html"):
        assert "design-home.js?v=20261021-mr1" in read(page), page
