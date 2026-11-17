/**
 * Conversations in the chat (BL-001).
 *
 * The panel on the left lists the person's conversations, grouped by date,
 * with a search by title and a menu per conversation (rename, archive,
 * delete). The bar above the chat shows the open conversation's title, which
 * can be edited in place. A conversation is created before its first turn,
 * so a turn that is stopped or fails is still kept in it; once the first
 * answer is on screen, the conversation_title system agent names it.
 * Opening one draws its messages with the same renderer as a live answer.
 * The URL follows the open conversation: /<company>/chat/<id>.
 *
 * Calls go through their own fetch: callToolkit replaces the abort
 * controller of the turn in progress.
 */
(function (global) {
    'use strict';

    const PAGE_SIZE = 50;
    const SEARCH_DELAY_MS = 250;

    const state = {
        currentId: null,
        currentTitle: '',
        items: [],
        hasMore: false,
        loading: false,
        archived: false,
        search: '',
        titled: new Set(),
        welcomeHtml: '',
    };

    function t(key, fallback) {
        if (typeof global.t_js === 'function') {
            const text = global.t_js(key);
            if (text && text !== key) return text;
        }
        return fallback || key;
    }

    function baseUrl() {
        const base = (global.iatoolkit_base_url || '').replace(/\/+$/, '');
        const company = (global.companyShortName || '').replace(/^\/+|\/+$/g, '');
        return `${base}/${company}`;
    }

    async function api(method, path, body) {
        const options = { method, credentials: 'include', headers: {} };
        if (body !== undefined) {
            options.body = JSON.stringify(body);
            options.headers['Content-Type'] = 'application/json';
        }
        const response = await fetch(`${baseUrl()}/api/conversations${path || ''}`, options);
        if (response.status === 401) {
            global.location.assign(`${baseUrl()}/home?session_expired=1`);
            return null;
        }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(data.error_message || `HTTP ${response.status}`);
            error.status = response.status;
            throw error;
        }
        return data;
    }

    // ------------------------------------------------------------------ the list
    function groupOf(isoDate) {
        const date = new Date(isoDate);
        if (isNaN(date)) return 'older';
        const today = new Date();
        const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
        const days = Math.round((startOfDay(today) - startOfDay(date)) / 86400000);
        if (days <= 0) return 'today';
        if (days === 1) return 'yesterday';
        if (days < 7) return 'week';
        if (date.getFullYear() === today.getFullYear() && date.getMonth() === today.getMonth()) return 'month';
        return 'older';
    }

    const GROUP_LABELS = {
        today: ['conv_group_today', 'Hoy'],
        yesterday: ['conv_group_yesterday', 'Ayer'],
        week: ['conv_group_week', 'Últimos 7 días'],
        month: ['conv_group_month', 'Este mes'],
        older: ['conv_group_older', 'Anteriores'],
    };

    function titleOf(item) {
        return (item && item.title) || t('conv_new_title', 'Nueva conversación');
    }

    function menuFor(item) {
        const dropdown = $('<div>').addClass('dropdown conversation-item-menu');
        const toggle = $('<button type="button">')
            .addClass('btn btn-sm conversations-icon-button')
            .attr({ 'data-bs-toggle': 'dropdown', 'aria-expanded': 'false', 'aria-label': t('conv_menu', 'Opciones') })
            .append($('<i>').addClass('bi bi-three-dots').attr('aria-hidden', 'true'));
        const menu = $('<ul>').addClass('dropdown-menu dropdown-menu-end');
        const entry = (icon, key, fallback, handler, danger) => {
            const link = $('<button type="button">').addClass('dropdown-item' + (danger ? ' text-danger' : ''))
                .append($('<i>').addClass(`bi ${icon} me-2`).attr('aria-hidden', 'true'), document.createTextNode(t(key, fallback)))
                .on('click', (event) => { event.stopPropagation(); handler(); });
            menu.append($('<li>').append(link));
        };
        entry('bi-pencil', 'conv_rename', 'Renombrar', () => startRename(item.id));
        if (state.archived) {
            entry('bi-arrow-counterclockwise', 'conv_restore', 'Restaurar', () => setStatus(item.id, 'active'));
        } else {
            entry('bi-archive', 'conv_archive', 'Archivar', () => setStatus(item.id, 'archived'));
        }
        entry('bi-trash', 'conv_delete', 'Eliminar', () => remove(item.id), true);
        toggle.on('click', (event) => event.stopPropagation());
        return dropdown.append(toggle, menu);
    }

    /** The text with each occurrence of `query` marked, built from text nodes only. */
    function highlighted(text, query) {
        const element = $('<span>');
        const value = String(text || '');
        const needle = String(query || '').toLowerCase();
        if (!needle) return element.text(value);
        let index = 0;
        const lower = value.toLowerCase();
        while (index < value.length) {
            const found = lower.indexOf(needle, index);
            if (found < 0) {
                element.append(document.createTextNode(value.slice(index)));
                break;
            }
            if (found > index) element.append(document.createTextNode(value.slice(index, found)));
            element.append($('<mark>').text(value.slice(found, found + needle.length)));
            index = found + needle.length;
        }
        return element;
    }

    function renderList() {
        const list = $('#conversations-list').empty();
        if (!state.items.length && !state.loading) {
            const key = state.search ? ['conv_no_results', 'Sin resultados.']
                : state.archived ? ['conv_empty_archived', 'No hay conversaciones archivadas.']
                : ['conv_empty', 'Tus conversaciones aparecerán aquí.'];
            list.append($('<div>').addClass('conversations-empty').text(t(key[0], key[1])));
            return;
        }
        let lastGroup = null;
        state.items.forEach((item) => {
            const group = groupOf(item.last_message_at);
            if (group !== lastGroup) {
                const label = GROUP_LABELS[group];
                list.append($('<div>').addClass('conversations-group').text(t(label[0], label[1])));
                lastGroup = group;
            }
            const row = $('<div>').addClass('conversation-item').attr({ role: 'listitem', 'data-id': item.id, tabindex: 0 })
                .toggleClass('is-active', item.id === state.currentId);
            const text = $('<div>').addClass('conversation-item-text');
            text.append($('<span>').addClass('conversation-item-title').text(titleOf(item)).attr('title', titleOf(item)));
            // A search that matched inside the conversation shows where.
            const match = item.match;
            if (match && match.snippet) {
                text.append(highlighted(match.snippet, state.search).addClass('conversation-item-snippet'));
            }
            row.append(text, menuFor(item));
            const focus = match ? match.message_id : null;
            row.on('click', () => open(item.id, { focusMessageId: focus, force: !!focus }));
            row.on('keydown', (event) => {
                if (event.key === 'Enter') open(item.id, { focusMessageId: focus, force: !!focus });
            });
            list.append(row);
        });
    }

    async function loadList(reset = true) {
        if (state.loading) return;
        state.loading = true;
        try {
            const params = new URLSearchParams({ limit: PAGE_SIZE });
            if (state.archived) params.set('archived', '1');
            if (state.search) params.set('q', state.search);
            if (!reset && state.items.length) params.set('before', state.items[state.items.length - 1].last_message_at);
            const data = await api('GET', `?${params.toString()}`);
            if (!data) return;
            state.items = reset ? data.conversations : state.items.concat(data.conversations);
            state.hasMore = !!data.has_more;
        } catch (error) {
            console.error('conversations: list', error);
            if (global.toastr) global.toastr.error(t('conv_load_error', 'No se pudieron cargar las conversaciones.'));
        } finally {
            state.loading = false;
            renderList();
        }
    }

    function upsert(conversation, moveToTop) {
        if (!conversation || state.archived) return;
        const index = state.items.findIndex((item) => item.id === conversation.id);
        if (index >= 0) {
            state.items[index] = Object.assign({}, state.items[index], conversation);
            if (moveToTop) state.items.unshift(state.items.splice(index, 1)[0]);
        } else if (!state.search) {
            state.items.unshift(conversation);
        }
        renderList();
    }

    // ------------------------------------------------------------------ the open conversation
    function setCurrent(id, title, { pushUrl = true } = {}) {
        state.currentId = id;
        state.currentTitle = title || '';
        $('#conversation-title').text(id ? titleOf({ title }) : '');
        $('#conversation-rename-button').prop('hidden', !id);
        $('#chat-panel').toggleClass('has-title', !!id);
        $('#conversations-list .conversation-item').each(function () {
            $(this).toggleClass('is-active', this.getAttribute('data-id') === id);
        });
        if (pushUrl && global.history && global.history.replaceState) {
            const path = id ? `${baseUrl()}/chat/${id}` : `${baseUrl()}/chat`;
            global.history.replaceState({ conversationId: id }, '', path);
        }
    }

    function clearChat() {
        const chat = $('#chat-container');
        chat.empty();
        if (state.welcomeHtml) chat.append($(state.welcomeHtml));
    }

    // chat_main.js keeps these as top-level `let`/`const`: shared by name
    // between the page's scripts, but not properties of window.
    function turnInProgress() {
        return typeof isRequestInProgress !== 'undefined' && isRequestInProgress;
    }

    function stopTurnIfRunning() {
        if (!turnInProgress()) return true;
        if (!global.confirm(t('conv_switch_running', 'Hay una respuesta en curso. ¿Detenerla y cambiar de conversación?'))) {
            return false;
        }
        if (typeof abortCurrentRequest === 'function') abortCurrentRequest();
        return true;
    }

    function drawMessages(messages) {
        const chat = $('#chat-container');
        chat.empty();
        (messages || []).forEach((message) => {
            const before = chat.children().length;
            if (message.role === 'user') {
                const files = (message.attachments || []).map((a) => ({ file: { name: a.name || '', type: '' } }));
                displayUserMessage(message.content || '', true, message.content || '', files);
                if (message.stopped) {
                    const note = $('<div>').addClass('system-message')
                        .append($('<i>').addClass('bi bi-stop-circle me-2'), $('<span>').text(t('conv_stopped', 'Detenida antes de responder.')));
                    global.displayBotMessage(note);
                }
            } else if (message.role === 'assistant') {
                const chatStream = global.IATChatStream;
                const activity = chatStream && chatStream.savedActivity ? chatStream.savedActivity(message.activity) : null;
                global.processBotResponse({
                    answer: message.answer || '', parts: message.parts || [], assistant_message_id: message.id,
                }, { activity });
            } else {
                const error = $('<div>').addClass('error-section')
                    .append($('<i>').addClass('bi bi-exclamation-triangle'), $('<p>').text(message.content || ''));
                global.displayBotMessage(error);
            }
            // Tag what this message added, so a search can bring it into view.
            chat.children().slice(before, before + 1).attr('data-message-id', message.id);
        });
        chat.scrollTop(chat[0].scrollHeight);
    }

    function focusMessage(messageId) {
        const target = $(`#chat-container [data-message-id="${messageId}"]`);
        if (!target.length) return;
        target[0].scrollIntoView({ block: 'center' });
        target.addClass('search-hit');
        setTimeout(() => target.removeClass('search-hit'), 2500);
    }

    async function open(id, { force = false, focusMessageId = null } = {}) {
        if (!id || (!force && id === state.currentId)) { closeDrawer(); return; }
        if (!stopTurnIfRunning()) return;
        closeDrawer();
        try {
            const data = await api('GET', `/${encodeURIComponent(id)}/messages`);
            if (!data) return;
            setCurrent(data.conversation.id, data.conversation.title);
            drawMessages(data.messages);
            if (focusMessageId) focusMessage(focusMessageId);
        } catch (error) {
            console.error('conversations: open', error);
            if (global.toastr) global.toastr.error(t('conv_open_error', 'No se pudo abrir la conversación.'));
            if (error.status === 404) setCurrent(null, '');
        }
    }

    function startNew() {
        if (!stopTurnIfRunning()) return;
        closeDrawer();
        setCurrent(null, '');
        clearChat();
        $('#question').trigger('focus');
    }

    /** The conversation the next turn belongs to: created before its first turn. */
    async function ensureConversation(questionText) {
        if (state.currentId) return state.currentId;
        try {
            const data = await api('POST', '', { question: questionText || '', source: 'chat_ui' });
            if (!data) return null;
            setCurrent(data.conversation.id, data.conversation.title);
            upsert(data.conversation, true);
            return data.conversation.id;
        } catch (error) {
            // Without a conversation the turn still goes out, as before conversations.
            console.error('conversations: create', error);
            return null;
        }
    }

    /** After a turn: the list moves it to the top, and a new one gets its title. */
    async function afterTurn(responseData) {
        const id = state.currentId;
        if (!id) return;
        const conversation = responseData && responseData.conversation;
        if (conversation && conversation.id === id) {
            upsert(conversation, true);
        } else {
            const item = state.items.find((entry) => entry.id === id);
            if (item) upsert(Object.assign({}, item, { last_message_at: new Date().toISOString() }), true);
        }
        const answered = responseData && responseData.assistant_message_id;
        if (!answered || state.titled.has(id)) return;
        const source = conversation ? conversation.title_source : 'auto';
        if (source !== 'auto') return;
        state.titled.add(id);
        try {
            const data = await api('POST', `/${encodeURIComponent(id)}/title`);
            if (data && data.conversation) {
                upsert(data.conversation, false);
                if (state.currentId === data.conversation.id) {
                    setCurrent(data.conversation.id, data.conversation.title, { pushUrl: false });
                }
            }
        } catch (error) {
            console.error('conversations: title', error);
        }
    }

    // ------------------------------------------------------------------ actions
    function editInPlace(target, currentTitle, onSave) {
        const input = $('<input type="text">').addClass('form-control form-control-sm conversation-title-input')
            .val(currentTitle || '').attr('maxlength', 120);
        const original = target.contents().detach();
        const restore = () => { target.empty().append(original); };
        let done = false;
        const finish = async (save) => {
            if (done) return;
            done = true;
            const value = String(input.val() || '').trim();
            restore();
            if (save && value && value !== currentTitle) await onSave(value);
        };
        input.on('keydown', (event) => {
            if (event.key === 'Enter') { event.preventDefault(); finish(true); }
            if (event.key === 'Escape') { event.preventDefault(); finish(false); }
        });
        input.on('blur', () => finish(true));
        input.on('click', (event) => event.stopPropagation());
        target.empty().append(input);
        input.trigger('focus').trigger('select');
    }

    async function rename(id, title) {
        try {
            const data = await api('PATCH', `/${encodeURIComponent(id)}`, { title });
            if (!data) return;
            upsert(data.conversation, false);
            if (state.currentId === id) setCurrent(id, data.conversation.title, { pushUrl: false });
        } catch (error) {
            console.error('conversations: rename', error);
            if (global.toastr) global.toastr.error(error.message);
        }
    }

    function startRename(id) {
        const item = state.items.find((entry) => entry.id === id);
        const row = $(`#conversations-list .conversation-item[data-id="${id}"]`);
        if (!row.length) {
            if (id === state.currentId) startRenameCurrent();
            return;
        }
        editInPlace(row, titleOf(item), (title) => rename(id, title));
    }

    function startRenameCurrent() {
        if (!state.currentId) return;
        const id = state.currentId;
        editInPlace($('#conversation-title'), state.currentTitle, (title) => rename(id, title));
    }

    async function setStatus(id, status) {
        try {
            await api('PATCH', `/${encodeURIComponent(id)}`, { status });
            state.items = state.items.filter((item) => item.id !== id);
            renderList();
            if (status === 'archived' && state.currentId === id) startNew();
        } catch (error) {
            console.error('conversations: status', error);
            if (global.toastr) global.toastr.error(error.message);
        }
    }

    async function remove(id) {
        if (!global.confirm(t('conv_delete_confirm', '¿Eliminar esta conversación? No se puede deshacer.'))) return;
        try {
            await api('DELETE', `/${encodeURIComponent(id)}`);
            state.items = state.items.filter((item) => item.id !== id);
            renderList();
            if (state.currentId === id) startNew();
        } catch (error) {
            console.error('conversations: delete', error);
            if (global.toastr) global.toastr.error(error.message);
        }
    }

    // ------------------------------------------------------------------ panel
    function isMobile() {
        return global.matchMedia && global.matchMedia('(max-width: 767.98px)').matches;
    }

    /** On a phone the panel is a drawer over the chat. */
    function openDrawer() {
        $('.chat-body').addClass('conversations-open');
        $('#conversations-backdrop').prop('hidden', false);
    }

    function closeDrawer() {
        $('.chat-body').removeClass('conversations-open');
        $('#conversations-backdrop').prop('hidden', true);
    }

    function showArchived(archived) {
        state.archived = archived;
        $('#conversations-archived-banner').prop('hidden', !archived);
        $('#conversations-archived-button').prop('hidden', archived);
        $('#new-conversation-button').prop('disabled', archived);
        loadList(true);
    }

    function setCollapsed(collapsed) {
        $('.chat-body').toggleClass('conversations-collapsed', collapsed);
        try { global.localStorage.setItem('iatoolkit.conversations_collapsed', collapsed ? '1' : '0'); } catch (e) { /* private mode */ }
    }

    function init() {
        if (!$('#conversations-panel').length) return;
        state.welcomeHtml = $('#chat-container').html();
        let collapsed = false;
        try { collapsed = global.localStorage.getItem('iatoolkit.conversations_collapsed') === '1'; } catch (e) { /* private mode */ }
        setCollapsed(collapsed);

        $('#new-conversation-button').on('click', startNew);
        $('#conversations-collapse-button').on('click', () => (isMobile() ? closeDrawer() : setCollapsed(true)));
        $('#conversations-open-button').on('click', () => (isMobile() ? openDrawer() : setCollapsed(false)));
        $('#conversations-backdrop').on('click', closeDrawer);
        $('#conversations-archived-button').on('click', () => showArchived(true));
        $('#conversations-back-button').on('click', () => showArchived(false));
        // Turns from before conversations: chat_history_button.js opens the history modal.
        $('#conversations-history-button').on('click', closeDrawer);
        $('#conversation-rename-button').on('click', startRenameCurrent);
        $('#conversation-title').on('dblclick', startRenameCurrent);

        let searchTimer = null;
        $('#conversations-search-input').on('input', function () {
            clearTimeout(searchTimer);
            const value = String(this.value || '').trim();
            searchTimer = setTimeout(() => { state.search = value; loadList(true); }, SEARCH_DELAY_MS);
        });
        $('#conversations-list').on('scroll', function () {
            if (state.hasMore && !state.loading && this.scrollTop + this.clientHeight >= this.scrollHeight - 40) {
                loadList(false);
            }
        });

        loadList(true);
        if (global.initialConversationId) open(global.initialConversationId, { force: true });
    }

    global.IATConversations = {
        init, open, startNew, ensureConversation, afterTurn, loadList,
        currentId: () => state.currentId,
        _state: state,
    };

    $(init);
})(window);
