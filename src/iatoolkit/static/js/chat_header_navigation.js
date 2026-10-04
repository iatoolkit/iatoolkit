(function () {
    const actions = new Set([
        'history-button', 'memory-button', 'force-reload-button',
        'send-feedback-button', 'open-help-button', 'logout-button'
    ]);
    const storageKey = 'iatoolkit.pending_chat_action';
    const header = document.querySelector('[data-chat-header]');
    if (!header) return;
    const selectionKey = 'iatoolkit.chat_header_selection';
    function isCurrent(value) {
        return value && value.company === header.dataset.company && value.user === header.dataset.user &&
            Number.isFinite(value.created) && Date.now() - value.created >= 0 && Date.now() - value.created < 30000;
    }
    try {
        const selection = JSON.parse(sessionStorage.getItem(selectionKey) || 'null');
        sessionStorage.removeItem(selectionKey);
        if (isCurrent(selection)) window.chatHeaderSelection = selection;
    } catch (_) {}

    // Carry the current selection only across navigation within this workspace.
    const workspacePaths = ['chat', 'account', 'mcp-connections'].map(
        page => '/' + encodeURIComponent(header.dataset.company) + '/' + page
    );
    function rememberSelection(url) {
        if (url.origin !== location.origin || !workspacePaths.includes(url.pathname)) return;
        try {
            sessionStorage.setItem(selectionKey, JSON.stringify({
                company: header.dataset.company, user: header.dataset.user, created: Date.now(),
                model: window.currentLlmModel, reasoningEffort: window.currentLlmReasoningEffort
            }));
        } catch (_) {}
    }
    document.addEventListener('click', event => {
        const link = event.target.closest('a[href]');
        if (!link || link.target === '_blank' || event.button !== 0 ||
            event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        rememberSelection(new URL(link.href));
    });
    document.addEventListener('submit', event => {
        if (event.target instanceof HTMLFormElement) {
            rememberSelection(new URL(event.target.getAttribute('action') || location.href, location.href));
        }
    });

    if (header.dataset.accountPage === 'true') {
        header.addEventListener('click', event => {
            const link = event.target.closest('[data-chat-action]');
            if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            try {
                sessionStorage.setItem(storageKey, JSON.stringify({
                    company: header.dataset.company, user: header.dataset.user,
                    action: link.dataset.chatAction, created: Date.now()
                }));
            } catch (_) {
                // The link still returns to the chat when browser storage is unavailable.
            }
        });
        return;
    }

    // Registered after the chat's handlers, including its jQuery ready callbacks.
    $(function () {
        try {
            const pending = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
            sessionStorage.removeItem(storageKey);
            if (!isCurrent(pending) || !actions.has(pending.action)) return;
            document.getElementById(pending.action)?.click();
        } catch (_) {
            // A stale or invalid navigation intent must not prevent the chat from opening.
        }
    });
})();
