/* 공통 진행·완료 표시 (슬라이스 54)
 *
 * 운영자가 [저장]·[등록]을 눌렀을 때 아무 반응이 없으면 두 번 누른다. 실제로 그렇게
 * 중복 요청이 나가는 화면이 있었다. 그래서 **쓰기 요청을 자동으로 감지해** 진행 중임을
 * 알리고 끝나면 결과를 말한다.
 *
 * 각 화면 코드를 고치지 않는다 — fetch를 감싸는 것으로 전 화면에 동시에 걸린다.
 * 기존 화면들이 이미 하단 토스트를 쓰므로 이 표시는 **상단**에 둔다(겹치지 않게).
 *
 * 표시하지 않는 것: GET(조회는 시끄러울 뿐이다) · 인증 폴링 · **미리보기**(요청 본문
 * `preview:true` — 2026-08-15 추가). 미리보기가 저장과 같은 URL을 쓰는 화면이 있어
 * (용도별 최소 사양 등) URL만 보는 verb()로는 못 가른다 — 그 상태로는 미리보기가
 * "저장하는 중…" → "완료되었습니다"로 떠 아무것도 안 바뀌었는데 저장된 것처럼 보인다.
 * 반복되면 진짜 저장 때도 무시하게 되고(알람 피로), 거꾸로 미리보기만 하고 실제 저장을
 * 빼먹을 수도 있다. 그래서 화면이 알려주는 게 아니라 **이 파일이 요청 본문을 스스로
 * 읽는다**(아래 `isPreviewBody`) — 화면마다 "나는 미리보기다"를 기억하게 하면 다음에
 * 생기는 화면이 반드시 빠뜨린다. 배너가 사라진 자리는 그 화면이 자기 영역 안에서
 * 채운다(버튼 비활성 · 인라인 진행 표시 — 예: `templates/admin/usage_floors.html.j2`).
 */
(function () {
  if (window.__pcProgress) return;
  window.__pcProgress = true;

  var BAR_ID = "__pc_progress";
  var active = 0;

  function el() {
    var b = document.getElementById(BAR_ID);
    if (b) return b;
    b = document.createElement("div");
    b.id = BAR_ID;
    b.setAttribute("role", "status");
    b.setAttribute("aria-live", "polite");
    b.style.cssText =
      "position:fixed;top:0;left:50%;transform:translateX(-50%) translateY(-120%);" +
      "z-index:100000;display:flex;align-items:center;gap:9px;padding:9px 18px;" +
      "border-radius:0 0 12px 12px;font-size:13px;font-weight:800;color:#fff;" +
      "background:#141824;box-shadow:0 6px 20px rgba(0,0,0,.25);transition:transform .18s;" +
      "font-family:var(--font);max-width:92vw;";
    (document.body || document.documentElement).appendChild(b);
    return b;
  }

  function show(html, bg, hold) {
    var b = el();
    b.innerHTML = html;
    b.style.background = bg || "#141824";
    b.style.transform = "translateX(-50%) translateY(0)";
    clearTimeout(b._t);
    if (hold) b._t = setTimeout(hide, hold);
  }

  function hide() {
    var b = document.getElementById(BAR_ID);
    if (b) b.style.transform = "translateX(-50%) translateY(-120%)";
  }

  var SPIN =
    '<span style="width:13px;height:13px;border:2px solid rgba(255,255,255,.35);' +
    'border-top-color:#fff;border-radius:50%;display:inline-block;' +
    'animation:__pcspin .7s linear infinite;"></span>';
  var st = document.createElement("style");
  st.textContent = "@keyframes __pcspin{to{transform:rotate(360deg)}}";
  (document.head || document.documentElement).appendChild(st);

  /* 무엇을 하는 중인지 경로로 짐작한다 — "처리 중"보다 "저장 중"이 낫다 */
  function verb(url, method) {
    var u = String(url || "");
    if (/undo/.test(u)) return "되돌리는";
    if (method === "PATCH") return "저장하는";
    if (method === "DELETE") return "삭제하는";
    if (/dryrun/.test(u)) return "검증하는";
    if (/catalog-import\/apply/.test(u)) return "적재하는";
    if (/\/products(\?|$)/.test(u)) return "등록하는";
    if (/stock-inbound/.test(u)) return "입고 처리하는";
    if (/reviews?\//.test(u)) return "반영하는";
    if (/orders/.test(u)) return "주문을 처리하는";
    return "저장하는";
  }

  /* 서버가 준 문장을 그대로 쓴다 — 화면이 지어낸 말보다 정확하다 */
  function okText(j, fallback) {
    if (j && typeof j === "object") {
      var s = j.verdict || j.note || j.message;
      if (typeof s === "string" && s.trim()) return s.trim();
    }
    return fallback;
  }

  /* 실패도 **이유를 말한다.**
   *
   * FastAPI 는 두 모양으로 답한다:
   *   · 우리가 던진 400/403/404/409 → `detail` 이 문장 하나(한국어)
   *   · 형식 검증 실패(422)         → `detail` 이 **배열**
   *       [{type, loc:["body","supplier_id"], msg:"Input should be a valid integer", input:null}]
   *
   * 배열은 `typeof === "object"` 라 예전 코드가 두 번째 분기로 빠졌고,
   * `d.detail`·`d.error` 가 없어 빈 문자열 → 결국 **"오류 422"** 만 떴다.
   * 사용자가 "매입가 입력시 오류"라고 신고한 그 화면이 정확히 이 상태였다
   * (2026-08-05) — 무엇이 잘못됐는지 한 글자도 알려주지 않았다.
   *
   * 어느 항목이 왜 틀렸는지까지 적는다. `loc` 의 'body' 는 사람에게 의미가 없어 뺀다.
   */
  function errText(j, status, where) {
    var d = j && j.detail;
    if (typeof d === "string" && d.trim()) return d.trim();
    if (Array.isArray(d) && d.length) {
      return d.map(function (x) {
        var f = (x.loc || []).filter(function (k) {
          return k !== "body" && k !== "query" && k !== "path";
        }).join(".");
        return (f ? f + ": " : "") + (x.msg || "");
      }).join(" · ");
    }
    /* `detail` 이 객체인 경우 — `raise HTTPException(status, {...})` 로 사람이 읽을
     * 문장과 기계용 코드를 함께 보내는 곳이 32곳(전수 검사, 2026-08-15). 그 문장을
     * 담는 **키 이름이 둘로 갈린다**: `detail`(20곳 — 주문·환불·스왑·인계 등) 또는
     * `message`(10곳 — 공급처 중복 2 · 상품 삭제/유사상품 3 · 로그인 5). `error`
     * 는 32곳 **전부**에 기계용 코드로 함께 있다(예: `duplicate_name`).
     *
     * 예전 우선순위 `detail → error → message` 는 `message` 모양 10곳에서 `detail`
     * 이 없으니 바로 `error` 를 집어 **사람이 읽는 문장이 있는데도 코드를 보여줬다**
     * — 공급처 등록에서 중복 이름을 넣으면 상단 배너가 "! duplicate_name" 이고
     * 화면 패널은 정상 한글 문장이라, **같은 사건에 두 자리가 다른 말을 하고
     * 있었다**(확인자 실측, 2026-08-15). `detail` 은 그대로 최우선으로 둔다 — 20곳이
     * 이미 이 경로로 옳게 동작 중이므로 순서를 지킨다. 대신 `message` 를 `error`
     * 보다 앞으로 옮긴다. `detail`·`message` 어느 것도 없는 두 곳(주문 품절 ·
     * 추천 조건 부족)은 여전히 `error` 코드를 마지막 수단으로 보여준다 — 빈
     * 문자열이 되는 것보다는 낫다. */
    if (d && typeof d === "object") {
      var inner = String(d.detail || d.message || d.error || "").trim();
      if (inner) return inner;
    }
    /* **본문 맨 위도 본다.** `detail` 자체가 없는 응답(FastAPI의 HTTPException을
     * 거치지 않은 경우)이 통째로 "오류 409" 가 된다 — 422 의 `detail` 배열을 못
     * 읽어 "오류 422" 만 뜨던 것과 **같은 병**이다(2026-08-05 사용자 신고). 화면이
     * 서버 응답의 모양을 하나로 가정하면 다른 모양이 올 때마다 조용해진다.
     * (전수 검사, 2026-08-15 — 지금 이 저장소에서 이 경로에 실제로 닿는 응답은
     * 없다: `JSONResponse`로 `detail`을 직접 보내는 네 곳이 전부 문자열이라 위
     * 첫 분기에서 이미 걸린다. 그래도 같은 병이 다시 생기지 않게 위와 같은
     * 순서 — 사람이 읽는 키를 코드보다 앞에 — 를 미리 맞춰 둔다.) */
    var top = j && String(j.message || j.note || j.error || "").trim();
    if (top) return top;
    /* 그래도 읽을 문장이 없으면 **무엇이 실패했는지라도** 말한다.
     * "오류 409" 만 뜨면 운영자도 개발자도 어느 요청인지 몰라 추측만 하게 된다
     * (실제로 그 상태로 신고가 들어왔다 — 2026-08-07). */
    return "오류 " + status + (where ? " — " + where : "");
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /** 표시용 경로 — 오리진·질의는 빼고 어느 API 인지만 남긴다. */
  function path(u) {
    try { return new URL(u, location.origin).pathname; }
    catch (e) { return String(u || "").split("?")[0]; }
  }

  /* 이 요청이 "미리보기"인지 — 요청 본문을 읽어 스스로 판단한다(화면이 알려주지 않는다).
   *
   * `preview`는 이 저장소가 이미 쓰는 이름이다(새로 정하지 않았다 — 실측): 용도별
   * 최소 사양(`POST .../usage-floors/{id}`) · 상품 분류 변경(`.../part-type`) ·
   * 상품 병합(`.../merge`) 셋 다 저장과 **같은 URL**에 바디 `{..., preview: true|false}`
   * 로만 갈린다.
   *
   * 이 저장소의 쓰기 호출은 전부 `fetch(url, {body: JSON.stringify(...)})` 형태다
   * (`new Request()` 사용처 0곳 — 전수 검색으로 확인). 그래서 `init.body`는 항상
   * **문자열**이거나 아예 없다. FormData를 쓰는 옛 업로드 화면(csv-upload·price-import)
   * 처럼 문자열이 아닌 본문은 아래에서 그냥 `false`로 떨어진다 — **못 읽으면 기존처럼
   * 배너를 띄운다**(실패를 "미리보기였다" 쪽으로 삼키지 않는다. 안전한 기본값은
   * "배너를 켠다" 쪽이다 — 배너가 잘못 하나 더 뜨는 것이, 저장인데 진행 표시가 아예
   * 사라지는 것보다 낫다).
   */
  function isPreviewBody(init) {
    var b = init && init.body;
    if (typeof b !== "string") return false;
    try {
      var j = JSON.parse(b);
      return !!(j && j.preview === true);
    } catch (e) {
      return false;
    }
  }

  /* ── 비밀번호 재확인(reauth) ──────────────────────────────────────────────
   *
   * 기기 기억(「이 기기에서 로그인 유지」)으로 만든 세션은 `password_verified=false`라
   * OWNER_WRITE_PREFIXES 쓰기에서 미들웨어가 401 + `error:"reauth_required"`로 막는다
   * (api/auth.py · 2026-08-15 사장님 지시 "민감한 일엔 다시 묻는다").
   *
   * **서버만 지어져 있고 화면이 없었다**(2026-08-31 실측: reauth를 처리하는 화면 0곳).
   * 그래서 사장님은 "비밀번호 확인이 필요합니다"만 보고 확인할 방법이 없었다 —
   * 요청 승인·운영자 관리·일괄 등록 등 **11개 경로가 전부 같은 상태**였다.
   *
   * 화면마다 붙이지 않고 여기 한 곳에 둔다 — 이 래퍼가 이미 전 화면의 쓰기를 감싼다
   * (§단일 원천: 두 벌로 만들면 화면마다 다른 문장을 말한다).
   *
   * ⚠ 비밀번호는 **서버로 보내는 것 외에 아무 데도 두지 않는다** — 변수에 담아 두거나
   *   로그·배너에 싣지 않는다. 창이 닫히면 그 값은 사라진다.
   */
  var reauthPending = null;      // 창을 동시에 둘 띄우지 않는다

  function isReauth(j) {
    var d = j && j.detail;
    return !!(d && typeof d === "object" && d.error === "reauth_required");
  }

  function askPassword(msg) {
    return new Promise(function (resolve) {
      var back = document.createElement("div");
      back.setAttribute("style", "position:fixed;inset:0;z-index:2147483646;" +
        "background:rgba(38,35,30,.42);display:flex;align-items:center;justify-content:center");
      var box = document.createElement("div");
      box.setAttribute("style", "background:#fff;border-radius:10px;padding:20px 22px;" +
        "width:min(360px,92vw);box-shadow:0 12px 40px rgba(0,0,0,.28);" +
        "font:400 13px/1.5 'Pretendard',system-ui,sans-serif;color:#2b2721");
      var h = document.createElement("div");
      h.setAttribute("style", "font-weight:700;font-size:14.5px;margin-bottom:6px");
      h.textContent = "비밀번호 확인";
      var p = document.createElement("div");
      p.setAttribute("style", "font-size:12px;color:#6b645a;margin-bottom:13px");
      p.textContent = msg || "민감한 작업이라 비밀번호를 한 번 더 확인합니다.";
      var inp = document.createElement("input");
      inp.type = "password";
      inp.autocomplete = "current-password";
      inp.setAttribute("style", "width:100%;box-sizing:border-box;padding:9px 11px;" +
        "border:1px solid rgba(0,0,0,.22);border-radius:6px;font-size:13px");
      var err = document.createElement("div");
      err.setAttribute("style", "color:#b31b25;font-size:11.5px;min-height:16px;margin-top:6px");
      var row = document.createElement("div");
      row.setAttribute("style", "display:flex;gap:8px;justify-content:flex-end;margin-top:12px");
      var cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = "취소";
      cancel.setAttribute("style", "padding:8px 13px;border-radius:6px;cursor:pointer;" +
        "border:1px solid rgba(0,0,0,.18);background:#fff;font-size:12.5px");
      var ok = document.createElement("button");
      ok.type = "button";
      ok.textContent = "확인";
      ok.setAttribute("style", "padding:8px 15px;border-radius:6px;cursor:pointer;border:0;" +
        "background:#2b2721;color:#fff;font-size:12.5px;font-weight:600");
      row.appendChild(cancel); row.appendChild(ok);
      box.appendChild(h); box.appendChild(p); box.appendChild(inp);
      box.appendChild(err); box.appendChild(row);
      back.appendChild(box);
      document.body.appendChild(back);
      setTimeout(function () { inp.focus(); }, 30);

      var done = false;
      function close(val) {
        if (done) return;
        done = true;
        inp.value = "";                       // 값을 DOM 에 남기지 않는다
        document.removeEventListener("keydown", onKey, true);
        try { back.remove(); } catch (e) { back.parentNode.removeChild(back); }
        resolve(val);
      }
      function submit() {
        var v = inp.value;
        if (!v) { err.textContent = "비밀번호를 입력하세요"; inp.focus(); return; }
        close(v);
      }
      function onKey(e) {
        if (e.key === "Escape") { e.stopPropagation(); close(null); }
        else if (e.key === "Enter" && document.activeElement === inp) { e.preventDefault(); submit(); }
      }
      document.addEventListener("keydown", onKey, true);
      cancel.addEventListener("click", function () { close(null); });
      ok.addEventListener("click", submit);
      back.addEventListener("click", function (e) { if (e.target === back) close(null); });
    });
  }

  /* 성공하면 true. 취소·실패면 false — 호출자는 원래 응답을 그대로 돌려준다. */
  function runReauth() {
    if (reauthPending) return reauthPending;
    var msg = null;
    reauthPending = (function attempt() {
      return askPassword(msg).then(function (pw) {
        if (pw === null) return false;
        return _fetch("/api/admin/auth/reauth", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: pw })
        }).then(function (r) {
          if (r.ok) return true;
          // 틀렸으면 같은 창에서 다시 묻는다 — 서버 문장을 그대로 쓴다
          return r.json().then(function (j) { return j; }, function () { return null; })
            .then(function (j) {
              msg = errText(j, r.status, "비밀번호 확인");
              return attempt();
            });
        });
      });
    })();
    return reauthPending.then(
      function (v) { reauthPending = null; return v; },
      function () { reauthPending = null; return false; }
    );
  }

  var _fetch = window.fetch;
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var method = ((init && init.method) ||
      (typeof input === "object" && input && input.method) || "GET").toUpperCase();
    var write = method !== "GET" && method !== "HEAD";
    // 로그인·세션 확인은 사용자가 누른 '저장'이 아니다 — 조용히 지나간다
    //
    // /api/candidates/count 도 같은 부류다(2026-08-24 추가, S1 확인자 실측 결함).
    // POST 지만 SELECT 하나뿐이고 쓰지 않는다(api/candidates.py 전수 확인 —
    // INSERT·UPDATE·DELETE·commit 0곳, consult_sessions 기록은 /api/recommend 몫이지
    // 이 엔드포인트가 아니다). S1(mockups/mvp1/s1-session.html)이 이 URL을 셋으로 쓴다 —
    // 현재 조건 조회(doCount, 타이핑마다 300ms 디바운스) · 완화 칩 가상 조회(relaxChips,
    // "조건 하나를 빼면?" 을 Promise.all 로 병렬 조회) · 초기 1회 조회. 셋째는 preview
    // 개념이 아예 없고, 완화 칩 쪽은 preview 표시 없이 나가 **가장 늦게 끝난 가상 조회가
    // "완료" 배너로 뜨는 결함**이 있었다(사무용·40만원 입력 시 카드는 "630,000원부터
    // 가능"인데 상단 토스트는 "지금 조건으로 만들 수 있어요" — 정반대). 이 URL은 저장소
    // 전체에서 s1-session.html만 호출한다(grep 확인, 2026-08-24) — 다른 화면의 토스트
    // 용법을 건드리지 않는다. S1은 이 세 호출 모두 이미 자기 영역 안에 진행 표시가 있다
    // (완화 칩 "완화 효과를 세는 중…" 인라인 문구 · _pending · poolUnknown/srcBadge 실패
    // 표시) — 전역 배너는 겹치기만 하고 있었다. 완화 칩 쪽에만 `preview:true`(아래
    // isPreviewBody)를 붙이는 좁은 수정 대신 URL 자체를 quiet 로 분류한 이유: 이 URL은
    // body 값과 무관하게 **항상** 읽기 전용이라(용도별 최소 사양·분류 변경·병합처럼
    // "저장/미리보기 겸용"인 URL이 아니다) preview 규약보다 quiet 규약이 맞고, 초기
    // 조회처럼 애초에 preview 개념이 없는 호출까지 함께 잡힌다.
    var quiet = /\/auth\/(login|logout|me)\b/.test(url) ||
      /\/api\/candidates\/count\b/.test(url);
    // 미리보기(본문 preview:true)는 저장과 같은 URL을 쓸 수 있어 URL 패턴(verb())만으로는
    // 못 가른다 — 배너를 띄우지 않고, 화면이 자기 자리에서 진행을 보여준다(㉯ 확정,
    // 2026-08-15). 미리보기가 아닌 요청의 동작은 이 한 줄 추가 전과 동일하다.
    var preview = write && isPreviewBody(init);
    if (!write || quiet || preview) return _fetch.apply(this, arguments);

    active++;
    show(SPIN + "<span>" + verb(url, method) + " 중…</span>");
    var self = this, args = arguments;
    return _fetch.apply(self, args).then(
      function (res) {
        active--;
        // 본문을 읽어도 호출자가 다시 읽을 수 있게 복제해서 본다
        var clone = null;
        try { clone = res.clone(); } catch (e) { clone = null; }
        var done = function (j) {
          if (active > 0) return;                     // 뒤이은 요청이 있으면 그쪽이 표시한다
          if (res.ok) {
            show('<span style="font-size:15px;">✓</span><span>' +
                 esc(okText(j, "완료되었습니다")) + "</span>", "#1c7a4d", 3200);
          } else {
            show('<span style="font-size:15px;">!</span><span>' +
                 esc(errText(j, res.status, method + " " + path(url))) + "</span>",
                 "#b31b25", 6000);
          }
        };
        var read = clone
          ? clone.json().then(function (j) { return j; }, function () { return null; })
          : Promise.resolve(null);
        return read.then(function (j) {
          // ── 비밀번호 재확인이 필요하다면 묻고 **원래 요청을 다시 보낸다** ──
          //    화면은 이 일이 있었는지 모른다 — 성공 응답만 받는다.
          //    ⚠ 본문이 문자열·FormData 라 재시도가 안전하다(new Request() 사용처 0곳).
          if (res.status === 401 && isReauth(j)) {
            hide();
            return runReauth().then(function (okd) {
              if (!okd) { done(j); return res; }       // 취소 — 원래 401 을 그대로 준다
              active++;
              show(SPIN + "<span>" + verb(url, method) + " 중…</span>");
              return _fetch.apply(self, args).then(function (res2) {
                active--;
                var c2 = null;
                try { c2 = res2.clone(); } catch (e) { c2 = null; }
                var done2 = function (j2) {
                  if (active > 0) return;
                  if (res2.ok) {
                    show('<span style="font-size:15px;">✓</span><span>' +
                         esc(okText(j2, "완료되었습니다")) + "</span>", "#1c7a4d", 3200);
                  } else {
                    show('<span style="font-size:15px;">!</span><span>' +
                         esc(errText(j2, res2.status, method + " " + path(url))) + "</span>",
                         "#b31b25", 6000);
                  }
                };
                if (c2) c2.json().then(done2, function () { done2(null); });
                else done2(null);
                return res2;
              }, function (e2) { active--; throw e2; });
            });
          }
          done(j);
          return res;
        });
      },
      function (err) {
        active--;
        if (active <= 0) {
          show('<span style="font-size:15px;">!</span><span>연결 실패 — ' +
               esc(err && err.message ? err.message : "네트워크") + "</span>", "#b31b25", 6000);
        }
        throw err;
      }
    );
  };

  /* 화면이 자기 자리에서 오류를 보여줄 때도 **같은 문장**을 쓰게 내보낸다.
   * 두 벌로 만들면 진행 바와 toast 가 서로 다른 말을 한다(이 프로젝트의 고질병). */
  window.popcornProgress = { errText: errText, okText: okText };
})();
