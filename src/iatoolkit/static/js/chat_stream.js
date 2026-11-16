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
        if (!readable) return translate('chat_stream_thinking', 'Pensando…');
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
     * The answer as it is being written: reasoning, then the markdown of the
     * text so far, re-rendered at most every RENDER_INTERVAL_MS. Text a model
     * writes before asking for a tool becomes a grey line once the round ends
     * with tool calls. The final event replaces all of it (removeLiveTurn).
     */
    const RENDER_INTERVAL_MS = 80;

    class LiveTurn {
        constructor() {
            this.container = null;
            this.answer = null;
            this.reasoningCard = null;
            this.text = '';
            this.reasoning = '';
            this.renderTimer = null;
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

        _ensure() {
            if (this.container) return;
            const uniqueId = 'live-reasoning-' + Date.now();
            this.container = $('<div>').addClass('bot-message-container live-turn');
            const reasoningBlock = $(`
                <div class="reasoning-block d-none">
                    <button class="reasoning-toggle btn btn-sm btn-link text-decoration-none p-0"
                        type="button" data-bs-toggle="collapse" data-bs-target="#${uniqueId}"
                        aria-expanded="true" aria-controls="${uniqueId}">
                        <i class="bi bi-lightbulb me-1"></i> <span class="reasoning-toggle-label"></span>
                    </button>
                    <div class="collapse show mt-2" id="${uniqueId}">
                        <div class="reasoning-card"></div>
                    </div>
                </div>
            `);
            reasoningBlock.find('.reasoning-toggle-label').text(translate('show_reasoning', 'Ver razonamiento'));
            // While it is written, the reasoning shows its last lines only: no
            // scroll box of its own inside the chat's.
            this.reasoningCard = reasoningBlock.find('.reasoning-card').addClass('reasoning-live');
            this.preambles = $('<div>').addClass('live-preambles');
            this.answer = $('<div>').addClass('answer-section llm-output');
            this.container.append(reasoningBlock).append(this.preambles).append(this.answer);

            const spinner = $('#spinner');
            this._keepBottom(() => {
                if (spinner.length) spinner.before(this.container);
                else this._chat().append(this.container);
            });
        }

        appendReasoning(text) {
            if (!text) return;
            this._ensure();
            this.reasoning += text;
            this._keepBottom(() => {
                // Text, never HTML: the reasoning echoes tenant data.
                this.reasoningCard.text(this.reasoning);
                this.reasoningCard.closest('.reasoning-block').removeClass('d-none');
                this.reasoningCard[0].scrollTop = this.reasoningCard[0].scrollHeight;
            });
        }

        appendText(text) {
            if (!text) return;
            this._ensure();
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
            let html;
            if (window.marked && typeof window.marked.parse === 'function') {
                html = window.marked.parse(normalizeHtmlBlocks(this.text), { gfm: true, breaks: false });
            } else {
                html = $('<div>').text(this.text).html().replace(/\n/g, '<br>');
            }
            const safe = typeof window.sanitizeHtmlFragment === 'function'
                ? window.sanitizeHtmlFragment(html)
                : $('<div>').text(this.text).html();
            this._keepBottom(() => this.answer.html(safe));
        }

        /** A round ended. Its text, if it asked for tools, was a preamble. */
        endRound(hasToolCalls) {
            if (!hasToolCalls || !this.container) return;
            const preamble = this.text.trim();
            this.text = '';
            this.render();
            if (preamble) {
                this._keepBottom(() => this.preambles.append($('<p>').addClass('live-preamble').text(preamble)));
            }
        }

        hasContent() {
            return !!this.container && (this.text.trim() !== '' || this.reasoning.trim() !== '');
        }

        /** Stopped or failed before the final event: keep what was written. */
        markIncomplete() {
            if (!this.container) return;
            this.render();
            if (!this.hasContent()) {
                this.remove();
                return;
            }
            this.container.removeClass('live-turn').addClass('live-turn-incomplete');
        }

        remove() {
            if (this.renderTimer !== null) clearTimeout(this.renderTimer);
            this.renderTimer = null;
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
