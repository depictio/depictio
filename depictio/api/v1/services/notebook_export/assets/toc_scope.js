
(function () {
  var last = null;
  function tabItems(toc) {
    return Array.prototype.filter.call(toc.querySelectorAll('li'), function (li) {
      var a = li.querySelector(':scope > a');
      return a && /^#tab-/.test(a.getAttribute('href') || '');
    });
  }
  function current() {
    var tabs = document.querySelectorAll('section[id^="tab-"]'), cur = null;
    for (var i = 0; i < tabs.length; i++) {
      var h = tabs[i].querySelector(':scope > h1, :scope > h2, :scope > h3, :scope > h4');
      if (!h || !h.getClientRects().length) continue;
      if (h.getBoundingClientRect().top < window.innerHeight * 0.33) cur = tabs[i].id;
    }
    return cur || (tabs[0] && tabs[0].id) || null;
  }
  function scope() {
    var toc = document.getElementById('TOC');
    if (!toc) return;
    var id = current();
    if (!id || id === last) return;
    last = id;
    tabItems(toc).forEach(function (li) {
      var on = li.querySelector(':scope > a').getAttribute('href') === '#' + id;
      li.classList.toggle('dpx-toc-current', on);
      var ul = li.querySelector(':scope > ul');
      if (!ul) return;
      ul.style.display = on ? '' : 'none';
      li.classList.toggle('dpx-folded', !on);
    });
  }
  var queued = false;
  window.addEventListener('scroll', function () {
    if (queued) return;
    queued = true;
    window.requestAnimationFrame(function () { queued = false; scope(); });
  }, { passive: true });
  window.addEventListener('load', scope);
  document.addEventListener('dpx:reveal', function () { last = null; scope(); });
  setTimeout(scope, 700);
})();
