(function () {
  var KEY = 'nefrlearn_theme';
  var root = document.documentElement;

  function getPreferred() {
    var saved = localStorage.getItem(KEY);
    if (saved) return saved;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  root.dataset.theme = getPreferred();

  function syncBtn() {
    var btn = document.getElementById('themeToggle');
    if (!btn) return;
    var dark = root.dataset.theme === 'dark';
    btn.textContent = dark ? '☀' : '🌙';
    btn.title = dark ? 'Светлая тема' : 'Тёмная тема';
  }

  window.__toggleTheme = function () {
    var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem(KEY, next);
    root.dataset.theme = next;
    syncBtn();
  };

  document.addEventListener('DOMContentLoaded', syncBtn);
})();
