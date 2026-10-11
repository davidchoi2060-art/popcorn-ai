/* 고객 질문 원문 표시 — 관리자 화면 공용 (2026-10-11 품질관리 11번).
 * 서버가 `api/admin_raw_text.raw_view` 로 만든 {text, state, label} 을 그린다.
 * 짧은 원문은 그대로, 길면 앞부분만 보이고 「전체 보기」로 펼친다(<details>).
 * 화면 위 고지 한 줄은 서버가 준 `raw_notice` 를 그대로 쓴다(문구를 두 벌 두지 않는다). */
(function () {
  var LIMIT = 140;
  var css = '.raw-q{white-space:pre-wrap;word-break:break-word;color:var(--rv-ink);line-height:1.55}'
    + '.raw-q.off{color:var(--rv-faint)}'
    + '.raw-q details summary{cursor:pointer;list-style:none}'
    + '.raw-q details summary::-webkit-details-marker{display:none}'
    + '.raw-q details summary .raw-more{color:var(--rv-link,var(--rv-ink-soft));text-decoration:underline;margin-left:4px;white-space:nowrap}'
    + '.raw-q details[open] summary .raw-pre{display:none}'
    + '.raw-q details[open] summary .raw-more::after{content:"접기"}'
    + '.raw-q details:not([open]) summary .raw-more::after{content:"전체 보기"}'
    + '.raw-notice{font-size:12.5px;color:var(--rv-ink-soft);background:var(--rv-panel2);border:1px solid var(--rv-dim4);border-radius:6px;padding:6px 10px;margin:0}';
  var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function html(v, prefix) {
    var head = prefix ? esc(prefix) : '';
    if (!v || v.state !== 'kept' || v.text == null) {
      return '<div class="raw-q off">' + head + esc((v && v.label) || '원문 기록 없음') + '</div>';
    }
    var t = String(v.text);
    if (t.length <= LIMIT) return '<div class="raw-q">' + head + esc(t) + '</div>';
    return '<div class="raw-q"><details><summary>' + head + '<span class="raw-pre">' + esc(t.slice(0, LIMIT)) + '…</span>'
      + '<span class="raw-more"></span></summary>' + esc(t) + '</details></div>';
  }
  function notice(text) { return text ? '<p class="raw-notice" role="note">' + esc(text) + '</p>' : ''; }
  window.RawText = { html: html, notice: notice, LIMIT: LIMIT };
})();
