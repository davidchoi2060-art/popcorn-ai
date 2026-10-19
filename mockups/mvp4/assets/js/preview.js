(function () {
  'use strict';
  var frame = document.getElementById('preview-frame');
  var picker = document.getElementById('preview-page');
  var openLink = document.querySelector('.preview-toolbar>a');
  document.querySelectorAll('[data-width]').forEach(function (button) {
    button.addEventListener('click', function () {
      frame.classList.toggle('is-mobile', button.dataset.width === 'mobile');
      frame.classList.toggle('is-tablet', button.dataset.width === 'tablet');
      document.querySelectorAll('[data-width]').forEach(function (item) {
        item.setAttribute('aria-pressed', String(item === button));
      });
    });
  });
  picker.addEventListener('change', function (event) {
    frame.src = event.target.value;
    openLink.href = event.target.value;
  });
  frame.addEventListener('load', function () {
    try {
      var url = new URL(frame.contentWindow.location.href);
      var path = url.pathname.split('/').pop();
      var value = path + url.search;
      var options = Array.from(picker.options);
      var match = options.find(function (option) { return option.value === value; }) ||
        options.find(function (option) { return option.value.split('?')[0] === path; });
      openLink.href = url.href;
      if (match) picker.value = match.value;
    } catch (error) {
      /* file:// iframe access can be restricted; relative navigation remains usable. */
    }
  });
}());
