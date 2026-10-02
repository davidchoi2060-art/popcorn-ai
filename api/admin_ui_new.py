"""NEW entry uses the existing auth gate, work queue and shared shell."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from .admin_ui_common import render
from .admin_nav import NAV

router = APIRouter(prefix='/admin2', tags=['admin-ui'])


@router.get('/new', response_class=HTMLResponse)
def home(request: Request):
    return render(request, 'admin/new_home.html.j2', screen_id='ADM-NEW-001',
                  domain='catalog', crumb_group='신 관리자', crumb_now='처리할 일', admin_mode='new')


@router.get('/new-settings', response_class=HTMLResponse)
def settings(request: Request):
    # Transitional access to existing tools. Never mark migrated/redesigned falsely.
    hidden = {'/admin2/', '/admin2/pc-workspace', '/admin2/pc-configurations',
              '/admin2/part-explanations', '/admin2/grid', '/admin2/game-matrix', '/admin2/build-map'}
    groups = [dict(title=title, items=[dict(label=label, href=href) for label, href, _ in items
                                     if href and href not in hidden]) for title, _, items in NAV]
    return render(request, 'admin/new_settings.html.j2', screen_id='ADM-NEW-002',
                  domain='settings', crumb_group='신 관리자', crumb_now='설정 · 자료 관리',
                  admin_mode='new', tool_groups=[g for g in groups if g['items']])
