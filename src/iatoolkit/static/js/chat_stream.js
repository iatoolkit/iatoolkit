// Live chat turn over Server-Sent Events (BL-023).
//
// The chat posts the same body it sends to /api/llm_query to
// /api/llm_query/stream and reads the events as they arrive: which tool is
// running, and the `final` event carrying the very JSON /api/llm_query
// returns, which the chat renders exactly as before. Only for the companies
// that turned it on (parameters.chat_streaming) and the providers whose
// adapters stream; every other turn goes through callToolkit as always.

(function () {
    const STREAMING_PROVIDERS = new Set(['openai', 'openrouter']);
    // No byte at all (the server sends a heartbeat every 15 s) for this long
    // means the connection is gone.
    const IDLE_TIMEOUT_MS = 90000;

    // Returned by run() when the stream endpoint is not there for this turn
    // (disabled, or the request never reached the server): the caller uses
    // the classic endpoint instead. Never returned once the turn started,
    // so a turn never runs twice.
    const FALLBACK = Object.freeze({ fallback: true });

    function translate(key, fallback) {
        if (typeof window.t_js !== 'function') return fallback;
        const value = window.t_js(key);
        return value && value !== key ? value : fallback;
    }

    function shouldStream(modelId) {
        if (window.chatStreamingEnabled !== true) return false;
        if (typeof ReadableStream === 'undefined' || typeof TextDecoder === 'undefined') return false;
        const models = Array.isArray(window.availableLlmModels) ? window.availableLlmModels : [];
        const model = models.find(m => m && m.id === modelId);
        const provider = String((model && model.provider) || '').trim().toLowerCase();
        return STREAMING_PROVIDERS.has(provider);
    }

    /** What the person sees for a tool: its translation, or its name made readable. */
    function toolLabel(name) {
        const raw = String(name || '').trim();
        const translated = translate('tool_' + raw, null);
        if (translated) return translated;
        const readable = raw.replace(/^iat_/, '').replace(/[_\-.]+/g, ' ').replace(/\s+/g, ' ').trim();
        if (!readable) return translate('chat_activity_thinking', 'Pensando…');
        return readable.charAt(0).toUpperCase() + readable.slice(1);
    }

    function streamUrl(apiPath) {
        const base = (window.iatoolkit_base_url || '').replace(/\/+$/, '');
        const company = (window.companyShortName || '').replace(/^\/+|\/+$/g, '');
        const path = apiPath.startsWith('/') ? apiPath : `/${apiPath}`;
        return `${base}/${company}${path}`;
    }

    /** Splits an SSE byte stream into {event, data} objects. */
    function createSseParser(onEvent) {
        let buffer = '';
        return function feed(text) {
            buffer += text.replace(/\r\n/g, '\n');
            let boundary = buffer.indexOf('\n\n');
            while (boundary !== -1) {
                const block = buffer.slice(0, boundary);
                buffer = buffer.slice(boundary + 2);
                let event = 'message';
                const dataLines = [];
                block.split('\n').forEach(line => {
                    if (!line || line.startsWith(':')) return;
                    const colon = line.indexOf(':');
                    const field = colon === -1 ? line : line.slice(0, colon);
                    const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '');
                    if (field === 'event') event = value;
                    else if (field === 'data') dataLines.push(value);
                });
                if (dataLines.length) {
                    let data = null;
                    try {
                        data = JSON.parse(dataLines.join('\n'));
                    } catch (e) {
                        console.warn('chat stream: unreadable event', event, e);
                    }
                    if (data !== null) onEvent(event, data);
                }
                boundary = buffer.indexOf('\n\n');
            }
        };
    }

    /**
     * Runs one turn over the stream.
     * @param {object} options
     *   data: the request body; signal: the AbortSignal of the stop button;
     *   handlers: {onEvent(event, data)} called for every event but `final`.
     * @returns {Promise<object|null|FALLBACK>} the final result, null when an
     *   error was already shown, or FALLBACK.
     */
    async function run({ apiPath, data, signal, handlers }) {
        let response;
        try {
            response = await fetch(streamUrl(apiPath), {
                method: 'POST',
                credentials: 'include',
                signal: signal,
                headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
                body: JSON.stringify(data),
            });
        } catch (error) {
            if (error && error.name === 'AbortError') throw error;
            // The request never reached the server: safe to try the classic way.
            return FALLBACK;
        }

        if (!response.ok) {
            if (response.status === 401) {
                const base = (window.iatoolkit_base_url || '').replace(/\/+$/, '');
                const company = (window.companyShortName || '').replace(/^\/+|\/+$/g, '');
                window.location.assign(`${base}/${company}/home?session_expired=1`);
                return null;
            }
            if ([403, 404, 405].includes(response.status)) {
                return FALLBACK;
            }
            let message = translate('unknown_server_error', 'Error desconocido del servidor.');
            try {
                const body = await response.json();
                message = body.error_message || body.error || message;
            } catch (e) { /* not JSON */ }
            throw new ChatStreamError(String(message));
        }

        const contentType = response.headers.get('Content-Type') || '';
        if (!contentType.includes('text/event-stream') || !response.body) {
            return FALLBACK;
        }

        let finalResult = undefined;
        let errorMessage = null;
        const parse = createSseParser((event, payload) => {
            if (event === 'final') {
                finalResult = payload;
            } else if (event === 'error') {
                errorMessage = payload.error_message || translate('processing_error', 'Ocurrió un error al procesar la solicitud.');
            } else if (handlers && typeof handlers.onEvent === 'function') {
                try {
                    handlers.onEvent(event, payload);
                } catch (e) {
                    console.error('chat stream: handler failed for', event, e);
                }
            }
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        try {
            while (true) {
                let idleTimer;
                const idle = new Promise((_, reject) => {
                    idleTimer = setTimeout(() => reject(new ChatStreamInterrupted()), IDLE_TIMEOUT_MS);
                });
                let chunk;
                try {
                    chunk = await Promise.race([reader.read(), idle]);
                } finally {
                    clearTimeout(idleTimer);
                }
                if (chunk.done) break;
                parse(decoder.decode(chunk.value, { stream: true }));
                // After `final` or `error` the server closes the stream itself;
                // reading on to the end keeps that from looking like a cancel.
            }
        } catch (error) {
            if (error && error.name === 'AbortError') throw error;
            try { reader.cancel(); } catch (e) { /* already closed */ }
            if (finalResult === undefined && errorMessage === null) throw new ChatStreamInterrupted();
        }

        if (errorMessage !== null) throw new ChatStreamError(errorMessage);
        if (finalResult === undefined) throw new ChatStreamInterrupted();
        return finalResult;
    }

    // Same rule as LLMClientService.normalize_html_blocks on the server: models
    // put an HTML block (a table) and markdown on consecutive lines, and indent
    // HTML; markdown then reads the markdown as HTML or the HTML as code.
    const HTML_BLOCK_TAGS = '(?:table|ul|ol|dl|div|pre|blockquote|p|h[1-6]|hr|section|details)';
    const BLOCK_INDENT = new RegExp(`^[ \\t]+(?=</?${HTML_BLOCK_TAGS}\\b)`, 'gim');
    const AFTER_CLOSING_BLOCK = new RegExp(`(</${HTML_BLOCK_TAGS}>)[ \\t]*\\n(?![ \\t]*\\n)`, 'gi');
    const BEFORE_OPENING_BLOCK = new RegExp(`([^\\n])\\n(?=<${HTML_BLOCK_TAGS}\\b)`, 'gim');

    function normalizeHtmlBlocks(text) {
        const parts = String(text || '').split(/(^```[\s\S]*?^```[ \t]*$)/m);
        for (let i = 0; i < parts.length; i += 2) {  // even parts are outside code fences
            parts[i] = parts[i]
                .replace(BLOCK_INDENT, '')
                .replace(AFTER_CLOSING_BLOCK, '$1\n\n')
                .replace(BEFORE_OPENING_BLOCK, '$1\n\n');
        }
        return parts.join('');
    }

    /**
     * A live turn (BL-023): the turn's activity above the answer, ChatGPT style.
     *
     * While it runs, one line ("Pensando… 8 s") and the step it is on (the title
     * of the reasoning summary, or the tool running); a click unfolds the
     * timeline of reasoning steps, tools and preambles. The answer is written
     * below, its markdown re-rendered at most every RENDER_INTERVAL_MS. When
     * the final event arrives the chat renders the final answer and keeps the
     * activity, collapsed ("Pensó durante 14 s · 2 herramientas"), above it.
     */
    const RENDER_INTERVAL_MS = 80;
    const REASONING_TITLE = /^\*\*(.+?)\*\*[ \t]*$/gm;

    function renderMarkdown(text) {
        let html;
        if (window.marked && typeof window.marked.parse === 'function') {
            html = window.marked.parse(normalizeHtmlBlocks(text), { gfm: true, breaks: false });
        } else {
            html = $('<div>').text(text).html().replace(/\n/g, '<br>');
        }
        return typeof window.sanitizeHtmlFragment === 'function'
            ? window.sanitizeHtmlFragment(html)
            : $('<div>').text(text).html();
    }

    function formatDuration(ms) {
        const seconds = Math.max(0, Math.round(ms / 1000));
        if (seconds < 60) return `${seconds} s`;
        const minutes = Math.floor(seconds / 60);
        return `${minutes} min ${String(seconds % 60).padStart(2, '0')} s`;
    }

    function fill(template, values) {
        return Object.keys(values).reduce((text, key) => text.split(`{${key}}`).join(values[key]), template);
    }

    /** Reasoning summaries come as "**Title**\n\ntext" sections. */
    function splitReasoning(text) {
        const steps = [];
        let lastIndex = 0;
        let current = { title: '', body: '' };
        REASONING_TITLE.lastIndex = 0;
        let match;
        while ((match = REASONING_TITLE.exec(text)) !== null) {
            current.body += text.slice(lastIndex, match.index);
            if (current.title || current.body.trim()) steps.push(current);
            current = { title: match[1].trim(), body: '' };
            lastIndex = match.index + match[0].length;
        }
        current.body += text.slice(lastIndex);
        if (current.title || current.body.trim()) steps.push(current);
        return steps;
    }

    let activitySequence = 0;

    class LiveTurn {
        constructor() {
            this.container = null;
            this.activity = null;
            this.answer = null;
            this.text = '';
            this.renderTimer = null;
            this.clock = null;
            this.startedAt = Date.now();
            this.finishedAt = null;
            this.items = [];          // timeline entries, in order
            this.reasoningItem = null; // the reasoning entry being written
            this.tools = {};          // call_id -> entry
            this.toolCount = 0;
            this.writing = false;
        }

        _chat() {
            return $('#chat-container');
        }

        _keepBottom(update) {
            const chat = this._chat()[0];
            const nearBottom = !chat || (chat.scrollHeight - chat.scrollTop - chat.clientHeight) < 120;
            update();
            if (chat && nearBottom) chat.scrollTop = chat.scrollHeight;
        }

        /** Shows the activity at once, in place of the spinner. */
        start() {
            if (this.container) return;
            const timelineId = 'turn-activity-' + (++activitySequence);
            this.container = $('<div>').addClass('bot-message-container live-turn');
            this.activity = $(`
                <div class="turn-activity is-running">
                    <button type="button" class="turn-activity-header" aria-expanded="false" aria-controls="${timelineId}">
                        <span class="turn-activity-indicator" aria-hidden="true"></span>
                        <span class="turn-activity-title"></span>
                        <span class="turn-activity-elapsed"></span>
                        <i class="bi bi-chevron-right turn-activity-chevron" aria-hidden="true"></i>
                    </button>
                    <div class="turn-activity-step" role="status" aria-live="polite"></div>
                    <ol class="turn-activity-timeline" id="${timelineId}" hidden></ol>
                </div>
            `);
            this.activity.find('.turn-activity-header').on('click', () => this.toggle());
            this.answer = $('<div>').addClass('answer-section llm-output');
            this.container.append(this.activity).append(this.answer);

            this._setTitle(translate('chat_activity_thinking', 'Pensando…'));
            this._tick();
            this.clock = setInterval(() => this._tick(), 1000);

            this._keepBottom(() => {
                const spinner = $('#spinner');
                if (spinner.length) {
                    spinner.before(this.container);
                    spinner.remove();
                } else {
                    this._chat().append(this.container);
                }
            });
        }

        toggle(open) {
            if (!this.activity) return;
            const header = this.activity.find('.turn-activity-header');
            const timeline = this.activity.find('.turn-activity-timeline');
            const expand = typeof open === 'boolean' ? open : header.attr('aria-expanded') !== 'true';
            header.attr('aria-expanded', expand ? 'true' : 'false');
            timeline.prop('hidden', !expand);
            this.activity.toggleClass('is-open', expand);
        }

        _setTitle(text) {
            this.activity.find('.turn-activity-title').text(text);
        }

        _setStep(text) {
            this.activity.find('.turn-activity-step').text(text || '');
        }

        _tick() {
            const end = this.finishedAt || Date.now();
            this.activity.find('.turn-activity-elapsed').text(formatDuration(end - this.startedAt));
        }

        _addItem(kind) {
            const item = { kind, element: $('<li>').addClass(`turn-activity-item is-${kind}`) };
            this.items.push(item);
            this.activity.find('.turn-activity-timeline').append(item.element);
            return item;
        }

        roundStart(round) {
            this.start();
            this.reasoningItem = null;
            if (round > 1 && !this.writing) this._setTitle(translate('chat_activity_thinking', 'Pensando…'));
        }

        appendReasoning(text) {
            if (!text) return;
            this.start();
            if (!this.reasoningItem) {
                this.reasoningItem = this._addItem('reasoning');
                this.reasoningItem.text = '';
            }
            const item = this.reasoningItem;
            item.text += text;
            const steps = splitReasoning(item.text);
            const element = item.element.empty();
            steps.forEach(step => {
                if (step.title) element.append($('<div>').addClass('turn-activity-item-title').text(step.title));
                if (step.body.trim()) element.append($('<div>').addClass('turn-activity-item-body').html(renderMarkdown(step.body.trim())));
            });
            const current = steps.length ? steps[steps.length - 1] : null;
            if (current && current.title && !this.writing) this._setStep(current.title);
        }

        toolStart(callId, name) {
            this.start();
            this.reasoningItem = null;
            const label = toolLabel(name);
            const item = this._addItem('tool');
            item.startedAt = Date.now();
            item.element.append(
                $('<span>').addClass('turn-activity-tool-status').attr('aria-hidden', 'true'),
                $('<span>').addClass('turn-activity-tool-label').text(label),
                $('<span>').addClass('turn-activity-tool-time'),
            );
            this.tools[callId || `tool-${this.items.length}`] = item;
            this.toolCount += 1;
            this._setStep(fill(translate('chat_stream_running_tool', '{tool}…'), { tool: label }));
        }

        toolEnd(callId, ok, ms) {
            const item = this.tools[callId];
            if (!item) return;
            const elapsed = typeof ms === 'number' ? ms : Date.now() - item.startedAt;
            item.element.addClass(ok ? 'is-ok' : 'is-error');
            item.element.find('.turn-activity-tool-time').text(formatDuration(elapsed));
            this._setStep('');
        }

        appendText(text) {
            if (!text) return;
            this.start();
            if (!this.writing) {
                this.writing = true;
                this._setTitle(translate('chat_stream_writing', 'Escribiendo la respuesta…'));
                this._setStep('');
            }
            this.text += text;
            if (this.renderTimer === null) {
                this.renderTimer = setTimeout(() => this.render(), RENDER_INTERVAL_MS);
            }
        }

        render() {
            if (this.renderTimer !== null) {
                clearTimeout(this.renderTimer);
                this.renderTimer = null;
            }
            if (!this.answer) return;
            const safe = renderMarkdown(this.text);
            this._keepBottom(() => this.answer.html(safe));
        }

        /** A round ended. Its text, if it asked for tools, was a preamble. */
        endRound(hasToolCalls) {
            this.reasoningItem = null;
            if (!hasToolCalls || !this.container) return;
            const preamble = this.text.trim();
            this.text = '';
            this.writing = false;
            this.render();
            this._setTitle(translate('chat_activity_thinking', 'Pensando…'));
            if (preamble) {
                const item = this._addItem('note');
                item.element.text(preamble);
                this._setStep(preamble);
            }
        }

        hasActivity() {
            return this.toolCount > 0 || this.items.some(item => item.kind === 'reasoning');
        }

        _finish(titleKey, fallback) {
            if (this.clock !== null) clearInterval(this.clock);
            this.clock = null;
            this.finishedAt = this.finishedAt || Date.now();
            this._tick();
            const seconds = formatDuration(this.finishedAt - this.startedAt);
            let title = fill(translate(titleKey, fallback), { duration: seconds });
            if (this.toolCount > 0) {
                const tools = this.toolCount === 1
                    ? translate('chat_activity_one_tool', '1 herramienta')
                    : fill(translate('chat_activity_tools', '{count} herramientas'), { count: this.toolCount });
                title += ' · ' + tools;
            }
            this.activity.removeClass('is-running').addClass('is-done');
            this.activity.find('.turn-activity-elapsed').text('');
            this._setTitle(title);
            this._setStep('');
            this.toggle(false);
        }

        /**
         * The final answer arrived: returns the activity, collapsed, for the
         * chat to keep above it (null when there was nothing to show), and
         * removes the live answer the final one replaces.
         */
        finish(finalReasoning) {
            if (!this.container) return null;
            if (!this.items.some(item => item.kind === 'reasoning') && finalReasoning) {
                this.appendReasoning(String(finalReasoning));
            }
            this._finish('chat_activity_done', 'Pensó durante {duration}');
            const activity = this.hasActivity() ? this.activity.detach() : null;
            this.remove();
            return activity;
        }

        /** Stopped or failed before the final event: keep what was written. */
        markIncomplete(stopped) {
            if (!this.container) return;
            this.render();
            this._finish(
                stopped ? 'chat_activity_stopped' : 'chat_activity_failed',
                stopped ? 'Detenido a los {duration}' : 'Se interrumpió a los {duration}',
            );
            if (!this.text.trim() && !this.hasActivity()) {
                this.remove();
                return;
            }
            if (!this.text.trim()) this.answer.remove();
            this.container.removeClass('live-turn').addClass('live-turn-incomplete');
        }

        remove() {
            if (this.renderTimer !== null) clearTimeout(this.renderTimer);
            if (this.clock !== null) clearInterval(this.clock);
            this.renderTimer = null;
            this.clock = null;
            if (this.container) this.container.remove();
            this.container = null;
        }
    }

    class ChatStreamError extends Error {
        constructor(message) {
            super(message);
            this.name = 'ChatStreamError';
        }
    }

    class ChatStreamInterrupted extends Error {
        constructor() {
            super(translate('chat_stream_interrupted', 'La respuesta se interrumpió antes de terminar. Intenta de nuevo.'));
            this.name = 'ChatStreamInterrupted';
        }
    }

    window.IATChatStream = {
        FALLBACK,
        shouldStream,
        toolLabel,
        run,
        createSseParser,
        createLiveTurn: () => new LiveTurn(),
        normalizeHtmlBlocks,
        ChatStreamError,
        ChatStreamInterrupted,
    };
})();
