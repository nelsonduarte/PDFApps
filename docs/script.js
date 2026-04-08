// Theme toggle with localStorage persistence
(function () {
    const KEY = 'pdfapps-theme';
    const html = document.documentElement;

    // Apply saved theme as early as possible to avoid FOUC
    const saved = localStorage.getItem(KEY);
    if (saved === 'light') {
        html.setAttribute('data-theme', 'light');
    }

    function applyTheme(theme) {
        if (theme === 'light') {
            html.setAttribute('data-theme', 'light');
        } else {
            html.removeAttribute('data-theme');
        }
        localStorage.setItem(KEY, theme);
        updateButton(theme);
    }

    function updateButton(theme) {
        const btn = document.getElementById('theme-toggle');
        if (!btn) return;
        const isLight = theme === 'light';
        btn.setAttribute('aria-label', isLight ? 'Switch to dark theme' : 'Switch to light theme');
        btn.innerHTML = isLight
            ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'
            : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
    }

    document.addEventListener('DOMContentLoaded', function () {
        const current = html.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
        updateButton(current);
        const btn = document.getElementById('theme-toggle');
        if (btn) {
            btn.addEventListener('click', function () {
                const next = html.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
                applyTheme(next);
            });
        }
    });
})();
