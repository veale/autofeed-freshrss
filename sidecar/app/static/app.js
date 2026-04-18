/* AutoFeed UI — app.js */

document.addEventListener('DOMContentLoaded', () => {
  initExampleLinks();
  initFlashMessages();
  initPreviewLoaders();
  initLazyPreviews();
  initClipboard();
  initDeleteConfirmations();
  initUrlSubmitShortcut();
});

// Fill the URL input when an example link is clicked
function initExampleLinks() {
  document.querySelectorAll('[data-example-url]').forEach(link => {
    link.addEventListener('click', e => {
      e.preventDefault();
      const input = document.querySelector('.url-input');
      if (input) {
        input.value = link.dataset.exampleUrl;
        input.focus();
      }
    });
  });
}

// Auto-dismiss flash messages after 4s; dismiss button removes immediately
function initFlashMessages() {
  document.querySelectorAll('.flash').forEach(flash => {
    const btn = flash.querySelector('.flash-dismiss');
    if (btn) {
      btn.addEventListener('click', () => removeFlash(flash));
    }
    setTimeout(() => removeFlash(flash), 4000);
  });
}

function removeFlash(el) {
  if (!el.isConnected) return;
  el.style.transition = 'opacity 0.35s';
  el.style.opacity = '0';
  setTimeout(() => el.remove(), 360);
}

// Progressively load preview fragments for [data-preview-url] targets
// Called on discover results page; no-op on home/other pages.
function initPreviewLoaders() {
  const targets = document.querySelectorAll('[data-preview-url]');
  if (targets.length === 0) return;

  // Mark every queued target with a subtle state
  targets.forEach(t => t.classList.add('preview-queued'));

  const queue = Array.from(targets);
  const maxConcurrent = 4;
  let active = 0;

  function next() {
    if (queue.length === 0 || active >= maxConcurrent) return;
    active++;
    const target = queue.shift();
    target.classList.remove('preview-queued');
    target.classList.add('preview-loading');
    fetch(target.dataset.previewUrl)
      .then(r => r.text())
      .then(html => {
        target.innerHTML = html;
        target.classList.remove('preview-loading');
      })
      .catch(e => {
        target.innerHTML = `<div class="preview-error">Preview failed: ${escapeHtml(e.message)}</div>`;
        target.classList.remove('preview-loading');
      })
      .finally(() => { active--; next(); });
  }

  for (let i = 0; i < maxConcurrent; i++) next();
}

// Click-to-load preview for non-auto-preview candidates
function initLazyPreviews() {
  document.addEventListener('click', e => {
    const btn = e.target.closest('.preview-btn');
    if (!btn || btn.disabled) return;

    const targetId = btn.dataset.target;
    const previewUrl = btn.dataset.previewUrl;
    if (!targetId || !previewUrl) return;

    const target = document.getElementById(targetId);
    if (!target) return;

    btn.disabled = true;
    btn.textContent = 'Loading…';
    target.innerHTML = '<div class="skeleton skeleton-preview"></div>';

    fetch(previewUrl)
      .then(r => r.text())
      .then(html => {
        target.innerHTML = html;
        btn.remove();
      })
      .catch(err => {
        target.innerHTML =
          '<div class="preview-error">Preview failed: ' + escapeHtml(err.message) + '</div>';
        btn.disabled = false;
        btn.textContent = 'Retry';
      });
  });
}

// Copy-to-clipboard buttons: [data-copy-text] or [data-copy-target="#selector"]
function initClipboard() {
  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-copy-text], [data-copy-target]');
    if (!btn) return;

    let text = btn.dataset.copyText;
    if (!text && btn.dataset.copyTarget) {
      const el = document.querySelector(btn.dataset.copyTarget);
      text = el ? el.textContent.trim() : '';
    }
    if (!text) return;

    if (!navigator.clipboard) {
      btn.textContent = 'Copy failed';
      return;
    }
    navigator.clipboard.writeText(text).then(() => {
      const orig = btn.textContent;
      btn.textContent = 'Copied';
      setTimeout(() => { btn.textContent = orig; }, 2000);
    }).catch(() => {
      btn.textContent = 'Copy failed';
    });
  });
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Safe delete confirmation using data-confirm attribute with JSON encoding
function initDeleteConfirmations() {
  document.addEventListener('submit', e => {
    const form = e.target.closest('form[data-confirm]');
    if (!form) return;
    try {
      const msg = JSON.parse(form.dataset.confirm);
      if (!confirm(msg)) {
        e.preventDefault();
      }
    } catch {
      // Fallback: if JSON parsing fails, use raw message
      if (!confirm(form.dataset.confirm)) {
        e.preventDefault();
      }
    }
  });
}

// Cmd/Ctrl+Enter submits the URL form on home page
function initUrlSubmitShortcut() {
  document.querySelector('.url-input')?.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.target.form.submit();
    }
  });
}
