"""기본형·고급형 업무 상세 5개 (2026-10-23 대표 승인 시안 적용).

업무 카드 → 해당 업무 상세(ai-service.html?package=basic|advanced&use=...) → 선택 업무·PC 의도를 유지한 도입 상담.
요청서: 코덱스-검수/2026-10-23-기본형-고급형-5개-업무상세-적용요청.txt
승인 ZIP: popcorn-basic-advanced-task-design-20261023.zip (SHA256 1f800d3b…b577b)
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

M = pathlib.Path(__file__).resolve().parents[1] / "mockups" / "mvp4"
V = "20261023-tg1"
TASKS = {"basic:study": "T", "basic:summary": "U", "basic:writing": "W", "advanced:image": "G", "advanced:code": "C"}


def read(rel):
    return (M / rel).read_text(encoding="utf-8")


# 사이트 공통 함수(P.h·P.icon)만 흉내 내고 ai-task-guides.js 를 그대로 실행해 다섯 화면의 실제 본문을 얻는다.
RENDER = r"""
const fs = require('fs'), vm = require('vm');
const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const PAI = {h: esc, icon: n => '<img class="icon" src="assets/icons/' + n + '.svg" alt="">', serviceGuides: {}};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {window: {PAI}});
const out = {};
for (const k of Object.keys(PAI.serviceGuides)) { const g = PAI.serviceGuides[k]; out[k] = {label: g.label, title: g.title, html: g.body(), mount: typeof g.mount}; }
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def rendered():
    node = shutil.which("node")
    if not node:
        pytest.skip("node 없음")
    with tempfile.TemporaryDirectory() as tmp:
        script = pathlib.Path(tmp) / "render.js"
        script.write_text(RENDER, encoding="utf-8")
        r = subprocess.run([node, str(script), str(M / "assets/js/ai-task-guides.js")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_cards_open_detail_before_consult():
    s = read("assets/js/ai.js")
    assert "var TASK_USES = {basic: {study: 1, summary: 1, writing: 1}, advanced: {image: 1, code: 1}};" in s
    assert "TASK_USES.hasOwnProperty(p.id) && TASK_USES[p.id][u.id] === 1 ? 'ai-service.html?package=' + p.id + '&amp;use=' + u.id" in s
    # 업무형 세 업무와 그 밖의 업무는 그대로
    assert "p.id === 'business' && SERVICE_USES[u.id] ? 'ai-service.html?package=business&amp;use=' + u.id" in s
    assert "link('ai-consult', {package:p.id, use:u.id})" in s
    # 패키지 데이터의 업무 id 와 같다
    data = read("assets/js/data.js")
    for key in TASKS:
        assert '"id": "%s"' % key.split(":")[1] in data, key


def test_service_page_loads_guides_and_keeps_site_shell():
    html = read("ai-service.html")
    assert 'data-page="ai-service"' in html and "header-ui.js?v=20261025-label1" in html
    assert "ai-task-guides.js?v=" + V in html and "ai-task-guides.css?v=" + V in html
    # core.js(P) 뒤, boot.js(렌더) 앞에서 등록된다
    assert html.index("core.js?v=") < html.index("ai-task-guides.js") < html.index("boot.js?v=")
    # 기존 업무형 세 설명은 그대로 실린다
    for asset in ("ai-meeting-guide.js?v=20261021-mm3", "ai-reply-guide.js?v=20261021-mm3", "ai-local-service.css?v=20261021-mm3"):
        assert asset in html, asset


def test_router_allows_only_known_package_use_pairs():
    s = read("assets/js/ai-local-service.js")
    assert "var PACKAGE_USES = {business: ['documents', 'meetings', 'replies'], basic: ['study', 'summary', 'writing'], advanced: ['image', 'code']};" in s
    assert "key = pkg === 'business' ? use : pkg + ':' + use" in s
    # 업무형만 PC 칸(ai-task-pc)과 기존 기업 컨설팅 링크를 끼운다. 새 업무는 본문 안에 같은 안내가 있다.
    assert "main + companyLink(use)" in s
    assert "if (pkg !== 'business')" in s
    assert "업무형 패키지의 사내 문서 검색·회의록 정리·고객 답변 초안 설명만" not in s


def test_five_guides_render_in_approved_order(rendered):
    assert sorted(rendered) == sorted(TASKS)
    # 시안 그대로 원문 보기 버튼은 왼쪽(내가 준비하는 것), 결과 탭은 오른쪽(검토할 결과) -- 둘 다 01 가상 예시 안에 있다
    order = ['id="tg-hero-title"', 'id="tg-example"', "data-tg-source", 'role="tablist"', 'id="tg-workflow"',
             'id="tg-scope"', 'id="tg-pc"', "tg-faq", 'id="tg-consult"', 'id="company-link"']
    for key, g in rendered.items():
        html = g["html"]
        pos = [html.index(x) for x in order]
        assert pos == sorted(pos), key
        assert g["mount"] == "function"
        assert html.count('data-tg-step="') == 5, key
        assert html.count('role="tab"') >= 2, key
        assert 'data-tg-pc="existing" aria-pressed="true"' in html and 'data-tg-pc="new" aria-pressed="false"' in html
        assert "<dialog" in html and 'aria-labelledby="tg-source-title"' in html
        pkg, use = key.split(":")
        assert 'src="assets/images/task-guides/%s.webp"' % use in html
        assert 'href="ai-detail.html?package=%s"' % pkg in html


def test_consult_links_keep_package_use_and_pc(rendered):
    for key, g in rendered.items():
        pkg, use = key.split(":")
        links = re.findall(r'href="(ai-consult\.html[^"]*)"', g["html"])
        assert len(links) == 2, key
        assert set(links) == {"ai-consult.html?package=%s&amp;use=%s&amp;intent=adoption&amp;pc=existing" % (pkg, use)}, key
        assert re.findall(r'href="(ai-company\.html[^"]*)"', g["html"]) == ["ai-company.html?from=" + TASKS[key]]


def test_design_only_parts_are_not_on_customer_screen(rendered):
    js = read("assets/js/ai-task-guides.js")
    for bad in ("design-switch", "plan-link", "review-label", "window.openai", "fetch(", "localStorage", "sessionStorage", "XMLHttpRequest"):
        assert bad not in js, bad
    for key, g in rendered.items():
        for bad in ("완전 오프라인", "업무 전환", "상담 연결 미리보기", "task-footer"):
            assert bad not in g["html"], (key, bad)
        assert "가상 예시" in g["html"] and "가상 원문" in g["html"]
        assert not re.search(r"\d[\d,]*\s*만?\s*원", g["html"]), key     # 가격·금액을 적지 않는다


def test_image_guide_does_not_claim_llm_only(rendered):
    html = rendered["advanced:image"]["html"]
    assert "별도의 이미지 생성 모델과 도구" in html
    assert "로컬 LLM과 실행 환경이 다르므로" in html


def test_keyboard_and_focus_behaviour_is_wired():
    js = read("assets/js/ai-task-guides.js")
    # 결과 탭: 화살표·Home·End, 선택 탭만 tabIndex 0
    assert "{ArrowLeft: -1, ArrowRight: 1, Home: 'first', End: 'last'}" in js
    assert "b.tabIndex = on ? 0 : -1" in js
    # 원문 모달: showModal(Esc 기본 닫힘) + 닫히면 연 버튼으로 초점 복귀
    assert "d.showModal()" in js and "dialog.addEventListener('close', function () { if (opener) opener.focus(); })" in js
    # PC 선택이 모든 상담 링크에 반영된다
    assert "each('[data-tg-consult]'" in js and "consultHref(t, pc)" in js


def test_company_routes_return_to_each_task():
    s = read("assets/js/company-routes.js")
    for key, f in TASKS.items():
        pkg, use = key.split(":")
        assert "%s: {href: 'ai-service.html?package=%s&use=%s#company-link'" % (f, pkg, use) in s, key
    for page in ("ai-company.html", "ai-consult.html", "ai-result.html", "review-ai-consult.html"):
        assert "company-routes.js?v=" + V in read(page), page


def test_consult_receives_pc_intent_without_new_form():
    s = read("assets/js/ai-inquiry.js")
    assert "var PC_PLANS = {existing:'existing', 'new':'bundle'}, pcArg = P.qs.get('pc');" in s
    assert "Object.prototype.hasOwnProperty.call(PC_PLANS, pcArg)" in s
    assert "setup:pcPlan || 'unsure'" in s
    assert "(pcPlan?'<fieldset class=\"iq-pc-plan\">" in s
    a = read("assets/js/service-adapters.js")
    assert "['PC 방향', p.intent === 'quote' ? '' : PC_PLAN[p.setup] || '']" in a
    for word in ("study: '학습 자료 정리'", "summary: '자료 요약'", "writing: '글쓰기 초안'", "image: '이미지 제작'", "code: '개발 보조'"):
        assert word in a, word
    for page in ("ai-consult.html", "ai-result.html", "review-ai-consult.html"):
        html = read(page)
        assert "ai-inquiry.js?v=" + V in html and "service-adapters.js?v=" + V in html, page


def test_task_images_are_light_webp_with_provenance():
    folder = M / "assets/images/task-guides"
    prov = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    text = json.dumps(prov, ensure_ascii=False)
    for key in TASKS:
        use = key.split(":")[1]
        f = folder / (use + ".webp")
        b = f.read_bytes()
        assert b[:4] == b"RIFF" and b[8:12] == b"WEBP", use
        assert len(b) < 200_000, use
        assert use + ".webp" in text, use
