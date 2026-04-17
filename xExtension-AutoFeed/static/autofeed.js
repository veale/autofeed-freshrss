document.addEventListener('DOMContentLoaded', function () {
	// Spinner: disable button and swap text on form submit
	document.querySelectorAll('[data-autofeed-spinner]').forEach(function (btn) {
		btn.closest('form').addEventListener('submit', function () {
			btn.disabled = true;
			var spinnerText = btn.getAttribute('data-spinner-text');
			if (spinnerText) {
				btn.textContent = spinnerText;
			}
		});
	});

	// Clipboard copy
	document.querySelectorAll('[data-autofeed-copy]').forEach(function (btn) {
		btn.addEventListener('click', function () {
			var selector = btn.getAttribute('data-autofeed-copy');
			var target = document.querySelector(selector);
			if (!target) return;
			navigator.clipboard.writeText(target.textContent).then(function () {
				var orig = btn.textContent;
				var copiedText = btn.getAttribute('data-copied-text') || 'Copied!';
				btn.textContent = copiedText;
				setTimeout(function () { btn.textContent = orig; }, 2000);
			});
		});
	});
});
