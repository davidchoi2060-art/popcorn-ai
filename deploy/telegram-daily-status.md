# 텔레그램 일일 현황 — 로컬 PC Windows 작업 스케줄러 (준비 문서)

> **방향 전환(2026-08-21) — 서버가 아니다.** 처음엔 서버 systemd timer로 설계했으나
> 사장님 결정("텔레그램 토큰을 서버에 안넣습니다")으로 **로컬 PC(이 저장소가 있는 PC)에서
> Windows 작업 스케줄러로 돌리는 쪽**으로 바뀌었다. 서버 `/etc/popcorn-ai.env`에는
> 아무것도 추가하지 않는다 — **손댈 서버 설정이 없다.**
>
> 이 문서는 **준비까지다.** 아래 명령은 하네스가 검토 후 직접 실행한다(제작자는 등록하지 않는다).

---

## 0. 왜 로컬에서 되는가 — 실측 근거

**① `scripts/status.py`는 DB에 직접 붙는다. 로컬 API 서버(8000)가 떠 있을 필요가 없다.**

```python
# scripts/status.py
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    ...
```

HTTP 호출(`requests`/`httpx`/`urllib`)이 스크립트 안에 전혀 없다 — SQLAlchemy로 `DATABASE_URL`에
바로 연결한다. 로컬 PC의 `.env`가 가리키는 DB는 **배포 서버와 같은 Cloud SQL**이므로(전역 규약에
있는 「로컬·배포 서버가 DB를 공유한다」그대로) 나오는 수치도 서버에서 돌리는 것과 같다.

**② `_tg_env.creds()`는 `.env`를 `__file__` 기준 절대경로로 찾는다 — 작업 디렉터리와 무관하다.**

```python
# scripts/_tg_env.py
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(ROOT, ".env")
```

`scripts/status.py`의 `sys.path.insert(...)`·`load_dotenv(...)`도 전부 같은
`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 패턴이다. **`__file__`이
이미 절대경로면(= 아래 명령처럼 python.exe와 스크립트를 전부 절대경로로 주면) 프로세스의
「시작 위치(작업 디렉터리)」는 결과에 영향을 주지 않는다.** 실측: `.env`·`.venv\Scripts\python.exe`
둘 다 `E:\DEV\popcorn-ai\`에 존재 확인(`test -f` 로 확인, 내용은 읽지 않음).

그래도 아래 등록 명령은 **모든 경로를 절대경로로** 써서 이 의존성 자체를 없앤다 — 관례상
"시작 위치"를 지정하고 싶다면 XML/PowerShell 경로가 필요하지만(§5 참고), 필수는 아니다.

**③ 서버 자격증명 확인은 이번 방향에서 무의미해졌다** — 애초에 로컬 `.env`에
`TELEGRAM_BOT_TOKEN`·`TELEGRAM_CHAT_ID`가 이미 있고(하네스 실측), 옮길 서버 설정이 없다.

---

## 1. 실제로 보내 본 결과 (2026-08-21 02:0x KST, 조용히·1회)

`_tg_env`가 `.env`를 읽는지, 인코딩이 깨지지 않는지 확인하려고 **실제 운영 명령과 같은 형태**를
`--silent`만 붙여 한 번 실행했다(사장님 취침 중이라 무음 — `send()`의 `disable_notification`을
그대로 노출하는 CLI 플래그가 있다: `--silent`).

```bash
.venv/Scripts/python.exe scripts/notify_telegram.py --title 현황 --silent \
  --run .venv/Scripts/python.exe scripts/status.py
```

결과: `보냄` 출력, 종료코드 `0` — `send()`는 텔레그램 `sendMessage` 응답의 `ok`가 참일 때만
이 줄까지 도달하므로(`api/../scripts/notify_telegram.py` `send()` 참조) **실제 전송 성공의
증거**다. 무음이라 사장님 폰에 소리·팝업 없이 도착했을 것이다(내용까지 육안 재확인은 못 함 —
봇이 보낸 메시지를 되읽는 API는 없다).

**인코딩 메모(중요 — 직접 겪음):** `.venv/Scripts/python.exe scripts/status.py`를
**감싸지 않고 단독으로** Git Bash에서 실행하면 한글이 깨진다(`PYTHONIOENCODING` 미설정 상태의
기본 콘솔 인코딩 때문 — cp949로 추정). 그런데 `notify_telegram.py --run`으로 감싸면 깨지지
않는다 — 이유는 `run_and_capture()`가 자식 프로세스에 `PYTHONUTF8=1`·`PYTHONIOENCODING=utf-8`을
**명시적으로 주입**하기 때문이다(`scripts/notify_telegram.py` 79~98행). 그리고 텔레그램으로
나가는 실제 바이트는 `send()`에서 `json.dumps(...).encode("utf-8")`로 **한 번 더 명시
인코딩**되므로 콘솔 코드페이지와 완전히 분리돼 있다. **즉 `--run`으로 감싸는 것 자체가
인코딩 방어책이다 — 감싸지 않은 단독 호출을 스케줄러에 등록하면 안 된다.**

남은 미확인 지점: Windows 작업 스케줄러가 python.exe를 직접 띄울 때 `--title 현황`이라는
인자가 콘솔을 거치지 않고 그대로 전달되는지는 **Git Bash 경유 테스트로 100% 같다고 증명하지
못한다**(스케줄러는 셸을 거치지 않고 CreateProcess를 직접 부른다 — 파이프를 거치는 PowerShell
문제와는 다른 경로다). Windows의 프로세스 인자 전달(`GetCommandLineW`)은 콘솔 코드페이지와
무관하게 유니코드로 넘어가는 것이 표준 동작이라 위험은 낮다고 판단하지만, **등록 후 1회는
`schtasks /Query ... /V /FO LIST`의 `Task To Run` 필드에 "현황"이 깨지지 않았는지, 그리고
실제 수신 문자를 눈으로 한 번 더 확인**하는 것을 권한다(§6 검증 참고).

---

## 2. 등록 명령 (하네스가 실행)

```
schtasks /Create /TN "PopcornAI-DailyStatus" /TR "E:\DEV\popcorn-ai\.venv\Scripts\python.exe E:\DEV\popcorn-ai\scripts\notify_telegram.py --title 현황 --run E:\DEV\popcorn-ai\.venv\Scripts\python.exe E:\DEV\popcorn-ai\scripts\status.py" /SC DAILY /ST 09:30 /RL LIMITED /F
```

- 경로 전부 절대경로 — `.venv\Scripts\python.exe`, `scripts\notify_telegram.py`,
  `scripts\status.py` 어디에도 공백이 없어 **인용부호 중첩 없이** 그대로 하나의 `/TR` 문자열로
  들어간다(따옴표 지옥 없음 — 그래서 경로에 공백 있는 다른 위치로 리포를 옮기면 이 명령이 깨진다).
- `--silent`는 **넣지 않았다** — 이건 매일 진짜로 사장님이 봐야 하는 알림이라 무음일 이유가 없다.
- `/RL LIMITED`: 관리자 권한 불필요(DB는 네트워크 접속, 텔레그램은 HTTPS 호출뿐) — 명시로 최소권한을 드러냄.
- `/F`: 이미 같은 이름 작업이 있으면 덮어쓴다(재실행 안전).
- "시작 위치(작업 디렉터리)"는 지정하지 않았다 — §0-②에서 확인했듯 불필요하다.
- 로그온 방식은 지정하지 않았다(`/RU`·`/RP` 없음) → 기본값 **"사용자가 로그온한 경우에만 실행"**,
  비밀번호를 어디에도 저장하지 않는다. 사장님 PC는 평소 로그인해 쓰는 PC라 이 기본값이 맞다.

## 3. 시각 제안 — **09:30 KST**, 근거

**피해야 할 것 — 백업 시각.** Cloud SQL 자동 백업이 **21:00 UTC = 06:00 KST**에 돈다
(`deploy/RESTORE.md` 22행, 실측 확인됨). 06:00 KST 부근은 피한다.

**피해야 할 것 — UTC/KST 날짜 경계 (직접 계산·실측으로 확인, 문서화된 적 없던 함정).**
`status.py`의 "오늘 상담"·"오늘 주문"은 `created_at::date = CURRENT_DATE`로 센다. **DB
세션 타임존은 UTC다**(이 저장소 여러 곳에서 이미 확인된 사실 — `api/session_scope.py` 25~31행
"DB 서버 세션 TimeZone 이 UTC(직접 확인: SHOW TIMEZONE → UTC)", `api/timeutil.py` 42~47행
동일 진술). **UTC 날짜가 바뀌는 시각은 KST로 09:00이다.** 즉:

    KST 00:00 ~ 08:59  "오늘"(CURRENT_DATE)이 아직 **KST 어제 날짜**를 가리킨다
                       → 이 구간에 돌리면 "오늘 상담/주문"이 사실은 어제 낮~밤 활동과 섞인 수치다
    KST 09:00 ~ 23:59  "오늘"이 KST 오늘과 일치한다 (그날 09:00 KST 이후 누적분)

이 저장소는 이 함정을 이미 여러 번 겪어 화면 조회 조건에서는 `api/timeutil.kst_day_range()`로
우회하고 있다(위 §0-①에 인용한 `timeutil.py` 주석 그대로 — "서울 하루 = UTC 15:00~15:00"
같은 문구가 회귀 `tests/regression.py` 2976행에도 있다). **그런데 `scripts/status.py`는 이
우회 없이 `CURRENT_DATE`를 그대로 쓴다** — 즉 지금 이 스크립트 자체가 그 함정 위에 있다.
제작자 담당 파일이 아니라 고치지 못했다 — §7 판단 항목에 제안으로만 남긴다.

**그래서 09:00 KST 이후로 잡아야 "오늘"이라는 라벨이 최소한 올바른 달력일을 가리킨다.**
09:00 정각은 UTC 자정과 동시라 오차 여지를 없애려고 **30분 여유를 두어 09:30**을 제안한다.
09:30~24:00 사이 어디든 이 문제는 없다 — "아침에 보고 싶다"는 취지에 맞춰 아침 쪽을 골랐다.
**이 시각은 취향 문제이지 정합성 문제가 아니다** — 원하시면 다른 시각(예: 10:00, 18:00)으로
바꿔도 위 제약(06:00 KST 근처 회피, 09:00 KST 이후) 안에서는 안전하다.

## 4. "PC 켤 때 실행" — StartWhenAvailable

`schtasks /Create`의 기본 플래그(`/SC`·`/ST` 등)에는 **"놓친 작업을 다음 부팅 때 실행"을 켜는
CLI 스위치가 없다**(직접 조사 — schtasks.exe 기본 문법에 존재하지 않는다. GUI의
"작업이 예약된 시작을 놓치면 최대한 빨리 실행"에 해당하는 내부 값은
`<Settings><StartWhenAvailable>true</StartWhenAvailable>`이고, XML 가져오기 또는
PowerShell `ScheduledTasks` 모듈로만 켤 수 있다). 손으로 XML을 새로 짜면 스키마 오타
위험이 크므로(등록 실패 메시지가 불친절하다), **더 안전한 방법**은 방금 만든 작업의
설정 하나만 PowerShell로 켜는 것이다 — 나머지 설정(schtasks가 만든 기본값)은 그대로 둔다:

```powershell
$t = Get-ScheduledTask -TaskName "PopcornAI-DailyStatus"
$t.Settings.StartWhenAvailable = $true
Set-ScheduledTask -InputObject $t | Out-Null
```

확인:

```powershell
(Get-ScheduledTask -TaskName "PopcornAI-DailyStatus").Settings.StartWhenAvailable
# True 가 나와야 한다
```

**추가로 고려할 만한 것(제안일 뿐, 필수 아님):** PC가 꺼진 게 아니라 **절전(잠자기)** 상태면
StartWhenAvailable만으로는 안 깨어난다 — `<WakeToRun>` 설정이 별도로 필요하다
(`$t.Settings.WakeToRun = $true`로 같은 방식). 사장님 PC가 밤에 절전 모드로 들어가는지
모르므로 판단 항목으로 남긴다(§7).

## 5. 검증 (등록 직후 1회)

```
schtasks /Query /TN "PopcornAI-DailyStatus" /V /FO LIST
```

확인할 항목:
- `Scheduled Task State` = `Enabled`
- `Start Time` = `9:30:00 AM`, `Schedule Type` = `Daily`
- `Task To Run` — 전체 명령이 그대로 나오는지, 특히 **"현황"이 깨지지 않았는지**(§1의 미확인 지점)
- `Repeat: Stop If Still Running` 등은 기본값으로 충분(이 작업은 몇 초짜리다)

## 6. 되돌리는 법

```
schtasks /Delete /TN "PopcornAI-DailyStatus" /F
```

삭제만 하면 된다 — 서버·DB·`.env` 어디에도 이 기능이 건드린 상태가 남지 않는다
(로컬 스케줄러 등록 그 자체가 전부다).

## 7. 실패 시 동작 — 조용히 넘어가는가, 남는가

**핵심 발견: 실패 종류에 따라 동작이 다르다.** `notify_telegram.py` 소스(`main()`)를 그대로 읽으면:

```python
if a.run:
    body, rc = run_and_capture(a.run)   # 자식이 죽어도 여기선 예외를 던지지 않는다
    ...
    body = body or "(출력 없음)"
...
send(body, silent=a.silent)             # 여기서 자격증명·네트워크 실패가 SystemExit
print("보냄")
if rc:
    sys.exit(rc)
```

- **`status.py`가 죽는 경우(DB 접속 실패 등)** — `run_and_capture()`는 예외를 삼키지 않되
  **호출자에게 (에러문구, 실패코드)를 그대로 돌려준다.** 그러면 `main()`은 그 에러문구를
  **본문으로 삼아 텔레그램 전송을 그래도 시도한다** — 즉 **이 경우는 조용히 안 넘어간다.
  사장님 폰에 에러 텍스트가 담긴 메시지가 그대로 간다.** 다만 `--title 현황`을 명시로 줬기
  때문에(코드상 "(실패 rc=…)" 접미사는 **제목을 안 줬을 때만** 자동으로 붙는다 —
  102~118행) 제목은 그냥 "현황"으로 오고 본문에서만 실패를 알 수 있다.
- **자격증명이 없거나 텔레그램 API 자체가 실패하는 경우** — `creds()`/`send()`가
  `SystemExit`을 던지고 **어디서도 잡지 않으므로 그대로 프로세스가 비정상 종료한다.**
  이 경우는 **정의상 메시지가 갈 수 없다**(발송 기능 자체가 고장났으므로). 토큰은 이
  경로에서도 절대 출력되지 않는다(`send()` 주석 "토큰은 절대 찍지 않는다").
  이 실패는 **로컬 PC에만 남는다** — `schtasks /Query /TN ... /V /FO LIST`의
  `Last Result`(0이 아니면 실패)로 확인 가능하고, Windows 이벤트 뷰어의
  작업 스케줄러 기록에도 남는다(단, "모든 작업 기록 사용"이 꺼져 있으면 상세 기록은
  안 쌓인다 — 꺼져 있으면 `schtasks /Query`만이 유일한 확인 창구가 된다).
  **사장님 입장에서는 "그날 아침 알림이 안 왔다"는 것 자체가 유일한 신호**이고, 그걸
  능동적으로 알리는 이중 채널은 없다(알림 실패를 알림으로 보고할 수는 없다 — 같은 통로가
  고장났으므로 당연한 한계다).

**요약**: 로직 실패(DB 등)는 **삼키지 않는다**(에러가 메시지로 옴). 발송 자체의 실패
(토큰·네트워크)는 **로컬에만 남고 사장님껜 안 간다** — 구조적 한계이지 만든 코드의
결함은 아니다(제작자 담당 파일 아님 — `scripts/notify_telegram.py`).

---

## 8. 함께 판단할 것 (제안만 — 결정은 사장님)

### 8-1. 현황 3줄이 지인·내부자 오픈 뒤에도 쓸모 있는가

지금 나오는 값(2026-08-21 02시경 1회 실측, 참고용 — 문서에 정본으로 박지 않는다):
`추천 후보`·`검수 대기`·`오늘 상담`·`오늘 주문`·`조립 표준 값(사람/제조사)`.

- **그대로 유용한 것**: 검수 대기(운영 백로그), 오늘 상담·오늘 주문(트래픽·전환 직결).
- **재검토 여지**: `조립 표준 값(사람 N·제조사 M)` — 이건 **카탈로그 구축 진행률** 성격이라
  오픈 전 내부 작업 지표에 가깝다. 오픈 후 "오늘 사업이 어떤가"와는 결이 다르다. 없애자는
  게 아니라 — 우선순위상 아래 항목보다 낮을 수 있다는 뜻이다.
- **빠진 것 — 이 프로젝트의 핵심 성공 지표가 안 보인다.** `CANON.md`가 명시한 이 시스템의
  존재 이유는 "고객 → 견적 → **팝콘PC 쇼핑몰로 인계**"다(판매하지 않는다 — 인계가 곧 성과).
  그런데 지금 3줄 어디에도 **인계(handoff)** 가 없다. 원장 테이블은 이미 있다
  (`handoffs`·`handoff_items`, `db/migrations/versions/0042_handoffs.py` 확인 —
  `handoffs.status`·`handoff_items.mall_status` 컬럼 존재). "오늘 인계 N건" 같은 한 줄이
  "오늘 상담 4건"과 나란히 있어야 **상담이 실제 성과로 이어졌는지**를 하루 단위로 볼 수 있다.
  지금 상태로는 상담만 보이고 그 다음 단계(인계 성공/실패)가 안 보인다.
- **추가로 고려할 만한 것**: "지인·내부자 오픈"이면 신규 운영자 신청도 늘 수 있다
  (`api/admin_operators.py` — 신청 대기 → owner 승인 흐름). "권한 신청 대기 N건" 같은
  줄이 있으면 사장님이 아침에 승인할 것이 있는지 바로 안다.
- **이건 제안이다** — `scripts/status.py`는 제작자 담당 파일이 아니라 고치지 않았다.

### 8-2. "오늘 상담 4건"을 어떻게 밝힐지

두 가지 원인이 섞여 있다(§3에서 이미 설명한 두 번째 원인은 새로 발견한 것):

1. **A-81 시험 운영 기간 제외** (기존에 알려진 원인) — `api/session_scope.py`가
   `scope_note()`라는, **바로 이 상황을 위해 이미 만들어진** 설명 문장 생성 함수를 갖고 있다
   ("이게 없으면 상담 4건이 무슨 뜻인지 아무도 모른다"는 그 코드 자신의 주석). `status.py`가
   이 함수를 안 쓰고 숫자만 낸다.
2. **UTC/KST 날짜 경계** (이번에 직접 계산해 새로 발견) — `CURRENT_DATE`가 UTC 기준이라
   09:00 KST 이전에 조회하면 "오늘"이 실제로는 KST 어제와 섞인다. 09:30 KST로 스케줄을
   잡으면(§3) 이 원인은 피해가지만, **누군가 낮에 수동으로 `status.py`를 돌려도 항상
   맞는다는 보장은 없다** — 근본 수정은 `CURRENT_DATE` 대신 `api/timeutil.kst_day_range()`
   패턴을 쓰는 것이다.

제안: 알림 본문에 `session_scope.scope_note()`(이미 존재하는 함수)를 한 줄 덧붙이면
원인 ①은 즉시 해소된다. 원인 ②는 `status.py`의 날짜 조건 자체를 고쳐야 하는 문제라
더 큰 변경이다. **둘 다 제안일 뿐 — 결정과 구현은 담당자(및 사장님) 몫이다.**

---

## 부록 — 수동 1회 테스트 명령 (참고용, 이미 §1에서 무음으로 실행해 성공 확인함)

```
E:\DEV\popcorn-ai\.venv\Scripts\python.exe E:\DEV\popcorn-ai\scripts\notify_telegram.py --title 현황 --run E:\DEV\popcorn-ai\.venv\Scripts\python.exe E:\DEV\popcorn-ai\scripts\status.py
```

(운영 알림이 실제로 필요할 때는 `--silent`를 빼고 이 명령 그대로 쓴다 — §2의 등록 명령과
`/TR` 내용이 동일하다.)
