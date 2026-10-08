# #1 Codex 기준bundle 인계 — 2026-10-08

역할: Claude workflow/runner, Codex 기준bundle/경로SHA/실제runtime핀. Claude앱수락착수는미확인. 번호별분담문서읽기. 기존운영workflow/제품/후보소스수정0. 지정OUT만작성.

정확복사8파일: api/__init__.py, api/admin_existing_pc_media.py, api/pc_existing_media_authority.py, api/pc_existing_media_import.py, api/pc_existing_media_refresh.py, tools/register_existing_pc_media.py, tests/test_existing_media_admin_flow_integration.py, tests/test_existing_media_pg_capture_plan_integration.py. 경로·rawSHA·크기·Gitblob구분은 bundle_manifest.json. 앞선부분bundle을완성. AST파싱PASS, unittestmethod18 정적열거(8+10)만확인/실행0. path및SHAallowlist외추가export0. env/개인정보/DBconfig/원제품사진/전체dirty복사0. lazy내부DB/auth/bound/snapshot과GCS는검사별mock/선택안된경로로제외. realSQLAlchemy text는사용되므로추가pin필수.

baseline2baa016. planner는PM이확정한checkoutraw9ab648ad...324ff 7902bytes/CRLF211를그대로복사. Gitblobc0c10a81...f0b74 7691bytes와raw다름/LF내용일치별도확인. 다른baseline5파일은raw/blob동일. newtest2는수용SHA904c11...df879/c7e323...7af40 일치. 모든bundle복사raw는현재정본checkout과일치. 미래PR에commit되는바이트는아직확인하지않았고LF변환가능하므로그때commit기준manifest를별도검증해야함. 제품원문정규화0.

requirements_ci.txt는DEV제품venv importlib.metadata실측16dependency핀. runtime-dependency-pins.json에출처. fastapi0.141.1/pydantic2.13.5/httpx0.28.1/sqlalchemy2.0.52 포함. Linux dependencyresolve/install은unknown, 일반AppDataPython fastapi실패반복조사0. pytest/conftest불필요/작성0.

Claude 전달조건: 기존unittest두파일정확18method명시수집, 필수누락/import실패/수집0/skip/expectedFailure/실패는green불가. runner가원manifest 경로/SHA검증, socket/subprocess차단(로컬ASGI/테스트합성임시파일허용), 결과JSON+summary. pg검사OUTPUT='D:/WORK/PopcornAI/outputs/existing-media-pg-capture-plan-code-mock-20261008'를그대로보존했으므로Linux실행에서는명시적임시경로adapter 또는안전한cwd하위경로준비필요; source몰래수정0. api/tools 패키지는소스에있는apiinit만복사, tools namespace import를사용하므로합성init추가0.

CI제안경계: github-hostedubuntu일회성/contentsread/checkoutpersistcredentialsfalse/dispatch전용후보. 공개repo운영selfhosted에PR트리거를연결하지않고기존deploy/regression수정및재사용0. workflow/runner본인은작성0. 운영비간섭소스근거는역할문서와앞선deploy.yml읽기이며현재운영설정실사또는cloud실행증거아님. PR/Actions/mainpush/권한/root/DBPG/restart/신규18실행/기존suite반복0.

선행조건: Claude초안및앱착수증거→후보문법/manifest/차단정적검수→cleancandidatecommit의바이트핀·변경범위→PR/Actions접근/기존runner분리조건확인→허용된cloud실행. 현재cloudREADY/CIgreen/실제네트워크차단/nativeDB/GCS/사용권한은미확인. 첫검색OSerror123과plannerraw불일치는initial-evidence/closure-source-mismatch에이력보존, PM명시재개와수용raw확정후현재묶음만완성했다.
