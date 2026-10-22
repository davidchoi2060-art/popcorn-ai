"""검색 로봇 안내 -- /robots.txt · /sitemap.xml (2026-10-22 오픈 전 점검: 둘 다 404 였다). `api/main.py` 가 자동으로 싣는다.

이 서버는 개발 서버(dev.popcornai.co.kr)다. 개발 화면이 검색에 잡히면 안 되므로 **기본은 전부 막는다**.
운영 서버에서만 SITE_INDEXING=on 을 두면 고객 화면(/mvp4/)만 열고 관리자·API·옛 화면은 막는다.
dev·admin 으로 시작하는 주소는 스위치와 관계없이 막는다(운영 설정을 개발 서버에 잘못 복사해도 새지 않게).
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

router = APIRouter()

# 검색에 내보낼 고객 화면 -- 결과·검수·이동용 화면(ai-detail·ai-consult·ai-result·bridge·review-*)은 noindex 라 넣지 않는다.
PUBLIC_PAGES = ("", "ai-packages.html", "ai-company.html", "ai-service.html", "supercomputers.html", "supercomputer.html",
                "supercomputer-inquiry.html", "peripherals.html", "support.html", "company.html", "terms.html",
                "privacy.html", "purchase-support.html")
CLOSED = "User-agent: *\nDisallow: /\n"


def indexing_open(request: Request) -> bool:
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host.startswith(("dev.", "admin.")) or not host:
        return False
    return (os.environ.get("SITE_INDEXING") or "").strip() == "on"


def _origin(request: Request) -> str:
    return "https://" + (request.headers.get("host") or "").split(":")[0].lower()


@router.get("/robots.txt", include_in_schema=False)
def robots(request: Request):
    if not indexing_open(request):
        return PlainTextResponse(CLOSED)
    body = ("User-agent: *\nAllow: /mvp4/\nDisallow: /admin2/\nDisallow: /admin/\nDisallow: /api/\n"
            "Disallow: /mvp1/\nDisallow: /mvp2/\nDisallow: /mvp3/\nSitemap: %s/sitemap.xml\n" % _origin(request))
    return PlainTextResponse(body)


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request):
    if not indexing_open(request):
        return Response(status_code=404)
    base = _origin(request) + "/mvp4/"
    urls = "".join("<url><loc>%s%s</loc></url>" % (base, p) for p in PUBLIC_PAGES)
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % urls
    return Response(xml, media_type="application/xml")
