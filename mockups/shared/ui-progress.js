/* 공통 진행·완료 표시 (슬라이스 54)
 *
 * 운영자가 [저장]·[등록]을 눌렀을 때 아무 반응이 없으면 두 번 누른다. 실제로 그렇게
 * 중복 요청이 나가는 화면이 있었다. 그래서 **쓰기 요청을 자동으로 감지해** 진행 중임을
 * 알리고 끝나면 결과를 말한다.
 *
 * 각 화면 코드를 고치지 않는다 — fetch를 감싸는 것으로 전 화면에 동시에 걸린다.
 * 기존 화면들이 이미 하단 토스트를 쓰므로 이 표시는 **상단**에 둔다(겹치지 않게).
 *
 * 표시하지 않는 것: GET(조회는 시끄러울 뿐이다) · 인증 폴링.
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
      "font-family:'Pretendard','Pretendard Variable',-apple-system,sans-serif;max-width:92vw;";
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
  function errText(j, status) {
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
    if (d && typeof d === "object") return String(d.detail || d.error || "").trim() || ("오류 " + status);
    return "오류 " + status;
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  var _fetch = window.fetch;
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var method = ((init && init.method) ||
      (typeof input === "object" && input && input.method) || "GET").toUpperCase();
    var write = method !== "GET" && method !== "HEAD";
    // 로그인·세션 확인은 사용자가 누른 '저장'이 아니다 — 조용히 지나간다
    var quiet = /\/auth\/(login|logout|me)\b/.test(url);
    if (!write || quiet) return _fetch.apply(this, arguments);

    active++;
    show(SPIN + "<span>" + verb(url, method) + " 중…</span>");
    return _fetch.apply(this, arguments).then(
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
                 esc(errText(j, res.status)) + "</span>", "#b31b25", 6000);
          }
        };
        if (clone) {
          clone.json().then(done, function () { done(null); });
        } else {
          done(null);
        }
        return res;
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
