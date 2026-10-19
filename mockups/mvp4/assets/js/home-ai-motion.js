/* A decorative introduction only: no AI execution, product recommendation,
 * request, price update, form submission, or customer input mutation occurs here.
 * Three use labels receive emphasis in order, one every 2.2 seconds (6.6s loop).
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P) return;
  var disposeCurrent = null;

  function mount() {
    var scene = document.querySelector('[data-home-ai-motion]');
    if (!scene || scene.dataset.motionMounted === 'true') return;
    if (disposeCurrent) disposeCurrent();
    var toggle = scene.querySelector('[data-home-ai-motion-toggle]');
    var keywords = Array.prototype.slice.call(scene.querySelectorAll('[data-home-ai-keyword]'));
    if (!toggle || keywords.length !== 3) return;
    scene.dataset.motionMounted = 'true';
    var preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    var userPaused = false, activeIndex = 0, timer = null, disposed = false;

    function emphasize() {
      keywords.forEach(function (keyword, index) {
        keyword.classList.toggle('is-active', index === activeIndex);
      });
    }
    function stopTimer() {
      if (timer !== null) { window.clearInterval(timer); timer = null; }
    }
    function synchronize() {
      if (disposed) return;
      var reduced = preference.matches;
      var paused = userPaused || reduced || document.hidden;
      stopTimer();
      scene.classList.toggle('is-paused', paused);
      scene.classList.toggle('is-reduced', reduced);
      toggle.disabled = reduced;
      toggle.setAttribute('aria-pressed', String(userPaused || reduced));
      toggle.textContent = reduced ? '정지 화면' : userPaused ? '모션 재생' : '모션 멈추기';
      toggle.setAttribute('aria-label', reduced ? '움직임 줄이기 설정으로 정지 화면을 표시합니다' : userPaused ? '소개 모션 재생' : '소개 모션 멈추기');
      if (!paused) {
        timer = window.setInterval(function () {
          if (document.hidden || preference.matches || userPaused) { synchronize(); return; }
          activeIndex = (activeIndex + 1) % keywords.length;
          emphasize();
        }, 2200);
      }
    }
    function handleToggle() {
      if (preference.matches) return;
      userPaused = !userPaused;
      synchronize();
    }
    function handlePageHide() { stopTimer(); scene.classList.add('is-paused'); }
    function dispose() {
      stopTimer(); disposed = true;
      toggle.removeEventListener('click', handleToggle);
      document.removeEventListener('visibilitychange', synchronize);
      window.removeEventListener('pagehide', handlePageHide);
      window.removeEventListener('pageshow', synchronize);
      if (typeof preference.removeEventListener === 'function') preference.removeEventListener('change', synchronize);
      else if (typeof preference.removeListener === 'function') preference.removeListener(synchronize);
      scene.classList.add('is-paused');
      delete scene.dataset.motionMounted;
    }

    toggle.addEventListener('click', handleToggle);
    document.addEventListener('visibilitychange', synchronize);
    window.addEventListener('pagehide', handlePageHide);
    window.addEventListener('pageshow', synchronize);
    if (typeof preference.addEventListener === 'function') preference.addEventListener('change', synchronize);
    else if (typeof preference.addListener === 'function') preference.addListener(synchronize);
    emphasize(); synchronize();
    disposeCurrent = dispose;
  }

  P.homeAiMotion = { mount: mount, destroy: function () { if (disposeCurrent) { disposeCurrent(); disposeCurrent = null; } } };
}());
