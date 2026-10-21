"""30인 이하 기업 컨설팅 화면·배선 (2026-10-21 승인 패킷).

업무형(P)·문서/회의/답변(D/M/R) -> 기업 설명(E) -> 기업 상담(C-E) 경로와
대상 범위 문구, 돌아가기 허용 목록, 상담 분류 표식을 고정한다.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "mockups" / "mvp4"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_company_page_exists_and_loads_its_assets():
    html = read("ai-company.html")
    assert 'data-page="ai-company"' in html
    assert "30인 이하" in html
    for asset in ("ai-company.css?v=20261021-co1", "company-routes.js?v=20261021-co1",
                  "ai-company.js?v=20261021-co1", "ai.js?v=20261021-co1"):
        assert asset in html, asset


def test_target_is_30_including_30_and_not_other_definitions():
    texts = read("assets/js/ai-company.js") + read("assets/js/ai.js") + read("assets/js/ai-inquiry.js") \
        + read("assets/js/ai-local-service.js") + read("ai-company.html")
    assert "30명 포함" in read("assets/js/ai-company.js")
    for bad in ("50인", "30인 미만", "소기업", "중소기업"):
        assert bad not in texts, bad


def test_return_allowlist_is_fixed_keys_only():
    s = read("assets/js/company-routes.js")
    keys = re.findall(r"\b([PDMR])\s*:\s*\{href:\s*'", s)
    assert sorted(keys) == ["D", "M", "P", "R"]
    for href in re.findall(r"href:\s*'([^']+)'", s):
        assert not href.startswith(("http", "//", "/")), href
        assert href.startswith(("ai-detail.html", "ai-service.html")), href
    assert "FALLBACK" in s
    # 외부 값은 키로만 쓰고 URL로 쓰지 않는다
    assert "location.href=" not in s.replace(" ", "")


def test_company_page_flow_and_honesty():
    s = read("assets/js/ai-company.js")
    assert "업무 예시 살펴보기" in s and "#company-case" in s
    assert "기업 컨설팅 상담하기" in s
    assert "AI 보조" in s and "사람 확인" in s
    assert "가상" in s
    for step in ("업무 파악", "현재 흐름도", "우선순위", "시범 적용", "확대"):
        assert step in s, step
    for bad in ("절감", "% 단축", "보안 보장", "성공 사례", "만원", "주 완성"):
        assert bad not in s, bad


def test_entry_split_on_business_page_only_and_no_dialog():
    s = read("assets/js/ai.js")
    assert "serviceChoice" in s and "service-choice" in s
    assert "ai-company.html?from=P" in s
    assert "p.id === 'business'" in s or "p.id==='business'" in s
    assert "dialog" not in s.split("serviceChoice", 1)[1].split("function", 1)[0]


def test_dmr_footer_links_keep_personal_cta():
    s = read("assets/js/ai-local-service.js")
    assert "COMPANY_FROM" in s and "company-link" in s
    for k in ("documents: 'D'", "meetings: 'M'", "replies: 'R'"):
        assert k in s, k
    assert "main + companyLink(use)" in s


def test_consult_company_mode_has_no_use_or_package_default():
    s = read("assets/js/ai-inquiry.js")
    assert "P.qs.get('service') === CR.SERVICE" in s
    assert "if(company)return companyForm(" in s
    assert "기업 컨설팅 상담" in s
    assert "service:company?CR.SERVICE:''" in s


def test_adapter_marks_company_message_without_fake_topic():
    s = read("assets/js/service-adapters.js")
    assert "[기업 AI 업무개선 컨설팅] 30인 이하 기업 대상" in s
    assert "p.service==='company'" in s.replace(" ", "")


def test_images_are_files_not_embedded_png():
    for rel in ("assets/js/ai-company.js", "assets/css/ai-company.css", "ai-company.html"):
        assert "data:image" not in read(rel), rel
    assert (ROOT / "assets/images/company/company-consulting-hero.jpg").exists()
    assert (ROOT / "assets/images/company/company-consulting-cta.jpg").exists()
    assert "가상" in read("assets/images/company/SOURCES.json")


def test_anchors_clear_fixed_header():
    css = read("assets/css/ai-company.css")
    assert "scroll-margin-top" in css
