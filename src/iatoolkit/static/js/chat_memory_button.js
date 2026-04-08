let memoryEditingCapture = null;
let memoryEditingRemovedItemIds = new Set();

$(document).ready(function () {
    const memoryModal = $('#memoryModal');
    const memoryDeleteConfirmModal = $('#memoryDeleteConfirmModal');
    const memoryCaptureInput = $('#memory-capture-input');
    const memoryExistingItems = $('#memory-existing-items');
    const memoryEditingBanner = $('#memory-capture-editing');
    let expandedMemoryId = null;
    let pendingDeleteCaptureId = null;
    const memoryFileInput = document.getElementById('memory-file-input');
    if (memoryFileInput && typeof window.createSharedFilePond === 'function') {
        window.memoryFilePond = window.createSharedFilePond(memoryFileInput, {
            allowMultiple: true,
            maxFiles: 5,
            labelIdle: t_js('memory_filepond_idle'),
        });
    }

    $('#memory-button').on('click', async function () {
        memoryModal.modal('show');
        await refreshMemoryDashboard();
    });

    $('#memory-run-lint-button').on('click', async function () {
        const button = $(this);
        const originalHtml = button.html();
        button.prop('disabled', true);
        button.addClass('is-loading');
        button.html(`<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${escapeHtml(t_js('memory_lint_running'))}`);
        await nextPaint();
        const response = await callToolkit('/api/memory', { action: 'lint' }, 'POST');
        button.prop('disabled', false);
        button.removeClass('is-loading');
        button.html(originalHtml);

        if (!response || response.status !== 'success') {
            toastr.error((response && response.error_message) || t_js('memory_lint_error'));
            return;
        }

        if (String(response.mode || '').trim() === 'inline') {
            toastr.success(t_js('memory_lint_success'));
        } else {
            toastr.success(t_js('memory_lint_scheduled'));
        }
        await refreshMemoryDashboard();
    });

    $('#memory-save-capture-button').on('click', async function () {
        const draft = await collectCaptureDraft();
        if (!draft) {
            toastr.info(t_js('memory_capture_required'));
            return;
        }

        const payload = memoryEditingCapture
            ? {
                action: 'update_capture',
                capture_id: memoryEditingCapture.capture_id,
                capture_text: draft.captureText,
                title: draft.title,
                keep_item_ids: draft.keepItemIds,
                items: draft.newItems,
            }
            : {
                action: 'save_capture',
                capture_text: draft.captureText,
                title: draft.title,
                items: draft.newItems,
            };

        const response = await callToolkit('/api/memory', payload, 'POST');
        if (!response || response.status !== 'success') {
            toastr.error((response && response.error_message) || t_js('memory_save_error'));
            return;
        }

        if ((draft.newItems || []).length || (draft.keepItemIds || []).length) {
            toastr.success(t_js('memory_save_success'));
        }
        resetCaptureEditor();
        await refreshMemoryDashboard();
    });

    $('#memory-pages-list').on('click', '.memory-page-card', async function () {
        const card = $(this);
        const pageId = $(this).data('pageId');
        if (!pageId) {
            return;
        }

        if (expandedMemoryId === pageId) {
            collapseInlineMemoryDetail();
            return;
        }

        const data = await callToolkit(`/api/memory/pages/${pageId}`, undefined, 'GET');
        if (!data || data.status !== 'success' || !data.page) {
            toastr.error(t_js('memory_open_error'));
            return;
        }

        collapseInlineMemoryDetail();
        expandedMemoryId = pageId;
        card.addClass('is-open');
        buildInlineMemoryDetail(data.page).insertAfter(card);
    });

    $('#memory-recent-list').on('click', '.memory-item-delete-button', async function (event) {
        event.preventDefault();
        event.stopPropagation();

        const button = $(this);
        pendingDeleteCaptureId = Number(button.data('captureId'));
        if (!pendingDeleteCaptureId) {
            return;
        }
        memoryDeleteConfirmModal.modal('show');
    });

    $('#memory-recent-list').on('click', '.memory-item-edit-button', function (event) {
        event.preventDefault();
        event.stopPropagation();
        const button = $(this);
        const capture = button.data('capture');
        if (!capture) {
            return;
        }
        beginCaptureEdit(capture);
    });

    $('#memory-existing-items').on('click', '.memory-existing-item-remove', function () {
        const button = $(this);
        const itemId = Number(button.data('itemId'));
        if (!itemId) {
            return;
        }
        if (memoryEditingRemovedItemIds.has(itemId)) {
            memoryEditingRemovedItemIds.delete(itemId);
        } else {
            memoryEditingRemovedItemIds.add(itemId);
        }
        renderExistingCaptureItems();
    });

    $('#memory-cancel-edit-button').on('click', function () {
        resetCaptureEditor();
    });

    $('#memory-confirm-delete-button').on('click', async function () {
        if (!pendingDeleteCaptureId) {
            memoryDeleteConfirmModal.modal('hide');
            return;
        }

        const confirmButton = $(this);
        confirmButton.prop('disabled', true);
        const deletedCaptureId = pendingDeleteCaptureId;
        const response = await callToolkit('/api/memory', {
            action: 'delete_capture',
            capture_id: deletedCaptureId
        }, 'POST');
        confirmButton.prop('disabled', false);

        if (!response || response.status !== 'success') {
            toastr.error((response && response.error_message) || t_js('memory_delete_error'));
            return;
        }

        pendingDeleteCaptureId = null;
        memoryDeleteConfirmModal.modal('hide');
        toastr.success(t_js('memory_delete_success'));
        if (memoryEditingCapture && memoryEditingCapture.capture_id === deletedCaptureId) {
            resetCaptureEditor();
        }
        await refreshMemoryDashboard();
    });

    memoryDeleteConfirmModal.on('hidden.bs.modal', function () {
        pendingDeleteCaptureId = null;
        $('#memory-confirm-delete-button').prop('disabled', false);
    });

    $('#memory-pages-list').on('click', '.memory-inline-close-button', function (event) {
        event.stopPropagation();
        collapseInlineMemoryDetail();
    });

    function collapseInlineMemoryDetail() {
        expandedMemoryId = null;
        $('#memory-pages-list').find('.memory-page-card').removeClass('is-open');
        $('#memory-pages-list').find('.memory-inline-detail').remove();
    }

    function beginCaptureEdit(capture) {
        memoryEditingCapture = capture;
        memoryEditingRemovedItemIds = new Set();
        memoryCaptureInput.val(buildEditableCaptureText(capture.items || []));
        memoryEditingBanner.text(t_js('memory_editing_capture')).show();
        $('#memory-cancel-edit-button').show();
        $('#memory-save-capture-button').html(`<i class="bi bi-check2 me-2"></i>${escapeHtml(t_js('memory_save_capture_changes'))}`);
        renderExistingCaptureItems();
    }

    function renderExistingCaptureItems() {
        if (!memoryEditingCapture) {
            memoryExistingItems.hide().empty();
            return;
        }
        const container = memoryExistingItems;
        container.empty().show();
        const removableItems = (memoryEditingCapture.items || []).filter(item => !isTextareaManagedCaptureItem(item));
        if (!removableItems.length) {
            container.hide().empty();
            return;
        }
        removableItems.forEach(item => {
            const removed = memoryEditingRemovedItemIds.has(item.id);
            const chip = $(`
                <div class="memory-existing-item ${removed ? 'is-removed' : ''}">
                    <span class="memory-existing-item-label"></span>
                    <button type="button" class="memory-existing-item-remove"></button>
                </div>
            `);
            chip.find('.memory-existing-item-label').text(item.filename || item.title || item.source_url || item.content_preview || t_js('memory_item_default'));
            chip.find('.memory-existing-item-remove')
                .attr('data-item-id', item.id)
                .text(removed ? t_js('memory_restore_item') : t_js('memory_remove_item'));
            container.append(chip);
        });
    }

    function resetCaptureEditor() {
        memoryEditingCapture = null;
        memoryEditingRemovedItemIds = new Set();
        memoryCaptureInput.val('');
        memoryEditingBanner.hide().empty();
        memoryExistingItems.hide().empty();
        $('#memory-cancel-edit-button').hide();
        $('#memory-save-capture-button').html(`<i class="bi bi-bookmark-plus me-2"></i>${escapeHtml(t_js('memory_save_capture'))}`);
        const pond = window.memoryFilePond;
        const nativeInput = document.getElementById('memory-file-input');
        if (pond) {
            pond.removeFiles();
        } else if (nativeInput) {
            nativeInput.value = '';
        }
    }
});

async function saveItemToMemory(payload, options = {}) {
    const response = await callToolkit('/api/memory', payload, 'POST');
    if (!response || response.status !== 'success') {
        toastr.error((response && response.error_message) || t_js('memory_save_error'));
        return null;
    }

    if (!options.silentSuccess) {
        toastr.success(t_js('memory_save_success'));
    }
    return response;
}

async function refreshMemoryDashboard() {
    $('#memory-loading').show();
    const data = await callToolkit('/api/memory', undefined, 'GET');
    $('#memory-loading').hide();

    if (!data || data.status !== 'success') {
        toastr.error(t_js('memory_load_error'));
        return;
    }

    renderRecentMemoryItems(data.captures || data.recent_items || []);
    renderMemoryPages(data.pages || []);
    renderMemoryLintSummary(data.last_lint || {});
}

function renderRecentMemoryItems(captures) {
    const container = $('#memory-recent-list');
    const empty = $('#memory-empty-recent');
    container.empty();

    if (!captures.length) {
        empty.show();
        return;
    }

    empty.hide();
    normalizeCaptureList(captures).forEach(capture => {
        const isPending = (capture.items || []).some(item => String(item.status || '').toLowerCase() !== 'compiled');
        const card = $(`
            <div class="memory-item-card">
                <div class="memory-item-shell d-flex justify-content-between align-items-start gap-3">
                    <div class="memory-item-main">
                        <div class="memory-item-copy">
                            <div class="memory-item-meta">
                                <div class="memory-item-icon" aria-hidden="true">
                                    <i class="${getMemoryCaptureIcon(capture)}"></i>
                                </div>
                                <div class="memory-item-timestamp"></div>
                                <span class="memory-item-pending-indicator" title="${escapeHtml(t_js('memory_item_pending_title'))}" aria-label="${escapeHtml(t_js('memory_item_pending_title'))}">
                                    <i class="bi bi-dot"></i>
                                </span>
                            </div>
                            <div class="memory-item-preview"></div>
                            <div class="memory-item-resources"></div>
                        </div>
                    </div>
                    <div class="memory-item-actions">
                        <button type="button" class="btn btn-sm memory-item-edit-button" title="${escapeHtml(t_js('memory_edit_item_title'))}" aria-label="${escapeHtml(t_js('memory_edit_item_title'))}">
                            <i class="bi bi-pencil"></i>
                        </button>
                        <button type="button" class="btn btn-sm memory-item-delete-button" title="${escapeHtml(t_js('memory_delete_item_title'))}" aria-label="${escapeHtml(t_js('memory_delete_item_title'))}">
                            <i class="bi bi-trash3"></i>
                        </button>
                    </div>
                </div>
            </div>
        `);
        card.find('.memory-item-edit-button').data('capture', capture);
        card.find('.memory-item-delete-button').attr('data-capture-id', capture.capture_id);
        card.find('.memory-item-preview').text(buildCapturePreview(capture));
        card.find('.memory-item-timestamp').text(formatMemoryCaptureTimestamp(capture.created_at));
        card.find('.memory-item-pending-indicator').toggle(isPending);
        renderCaptureResources(card.find('.memory-item-resources'), buildCaptureResources(capture));
        container.append(card);
    });
}

function renderMemoryPages(pages) {
    const container = $('#memory-pages-list');
    const empty = $('#memory-empty-pages');
    container.empty();

    if (!pages.length) {
        empty.show();
        return;
    }

    empty.hide();
    pages.forEach(page => {
        const card = $(`
            <button type="button" class="memory-page-card">
                <div class="d-flex justify-content-between align-items-start gap-3">
                    <div class="memory-page-copy">
                        <div class="memory-page-title"></div>
                        <div class="memory-page-summary"></div>
                    </div>
                    <div class="memory-page-open-hint">
                        <i class="bi bi-chevron-down"></i>
                    </div>
                </div>
            </button>
        `);
        card.data('pageId', page.page_id);
        card.find('.memory-page-title').text(page.title || t_js('memory_untitled'));
        card.find('.memory-page-summary').text(page.summary || t_js('memory_no_summary'));
        container.append(card);
    });
}

function renderMemoryLintSummary(lint) {
    const container = $('#memory-lint-summary');
    const checkedPages = Number(lint.checked_pages || 0);
    const actionsApplied = Number(lint.actions_applied || 0);
    const duplicateCandidates = Number(lint.duplicate_candidates || 0);
    const orphanPages = Number(lint.orphan_pages || 0);
    const timestamp = String(lint.timestamp || '').trim();

    if (!checkedPages && !timestamp) {
        container.hide().empty();
        return;
    }

    const chips = [
        `<span class="memory-lint-chip">${escapeHtml(t_js('memory_lint_checked').replace('{count}', String(checkedPages)))}</span>`,
        `<span class="memory-lint-chip">${escapeHtml(t_js('memory_lint_actions').replace('{count}', String(actionsApplied)))}</span>`,
        `<span class="memory-lint-chip">${escapeHtml(t_js('memory_lint_duplicates').replace('{count}', String(duplicateCandidates)))}</span>`,
        `<span class="memory-lint-chip">${escapeHtml(t_js('memory_lint_orphans').replace('{count}', String(orphanPages)))}</span>`,
    ].join('');

    const details = Array.isArray(lint.details) ? lint.details.filter(Boolean).slice(0, 3) : [];
    const detailsHtml = details.length
        ? `<ul class="memory-lint-details">${details.map(item => `<li>${escapeHtml(String(item))}</li>`).join('')}</ul>`
        : '';

    container.html(`
        <div class="memory-lint-title-row">
            <div class="memory-lint-title">${escapeHtml(t_js('memory_lint_last_title'))}</div>
            ${timestamp ? `<div class="memory-lint-timestamp">${escapeHtml(formatMemoryDate(timestamp))}</div>` : ''}
        </div>
        <div class="memory-lint-chips">${chips}</div>
        ${detailsHtml}
    `).show();
}

function buildInlineMemoryDetail(page) {
    const presentation = buildMemoryPresentation(page);
    const wrapper = $(`
        <div class="memory-inline-detail">
            <div class="d-flex justify-content-between align-items-start gap-3 memory-inline-header">
                <div class="memory-inline-heading">
                    <h6 class="memory-inline-title mb-0"></h6>
                    <div class="memory-inline-meta"></div>
                </div>
                <button type="button" class="memory-inline-close-button" title="${escapeHtml(t_js('memory_close'))}" aria-label="${escapeHtml(t_js('memory_close'))}">
                    <i class="bi bi-x-lg"></i>
                </button>
            </div>
            <div class="memory-inline-body"></div>
        </div>
    `);

    wrapper.find('.memory-inline-title').text(presentation.title);
    wrapper.find('.memory-inline-meta').html(renderMemoryMeta(presentation));
    const body = wrapper.find('.memory-inline-body');

    if (presentation.heroText) {
        body.append(`
            <section class="memory-inline-hero">
                <div class="memory-inline-hero-copy">${renderRichMemoryText(presentation.heroText)}</div>
            </section>
        `);
    }

    const sections = [
        renderMemoryBlock(t_js('memory_section_key_points'), presentation.keyPoints),
        renderMemoryBlock(t_js('memory_section_decisions'), presentation.decisions),
        renderMemoryBlock(t_js('memory_section_open_questions'), presentation.openQuestions),
        renderMemoryBlock(t_js('memory_section_next_steps'), presentation.nextSteps),
    ].filter(Boolean);

    sections.forEach(section => body.append(section));

    const sourcesSection = renderMemorySources(presentation.sources);
    if (sourcesSection) {
        body.append(sourcesSection);
    }

    if (!presentation.heroText && !sections.length && !sourcesSection) {
        body.append(`<div class="memory-inline-empty">${escapeHtml(t_js('memory_empty_inline'))}</div>`);
    }
    return wrapper;
}

function renderMemoryBlock(title, entries) {
    const normalized = Array.isArray(entries) ? entries.filter(Boolean) : [];
    if (!normalized.length) {
        return '';
    }

    const listTag = title === 'Resumen' ? 'div' : 'ul';
    const bodyHtml = listTag === 'ul'
        ? `<ul>${normalized.map(item => `<li>${renderRichMemoryText(String(item))}</li>`).join('')}</ul>`
        : `<div class="memory-block-copy">${renderRichMemoryText(String(normalized[0]))}</div>`;
    return `
        <section class="memory-page-block">
            <div class="memory-block-title">${escapeHtml(title)}</div>
            ${bodyHtml}
        </section>
    `;
}

function renderMemorySources(sources) {
    const normalized = Array.isArray(sources) ? sources.filter(Boolean) : [];
    if (!normalized.length) {
        return '';
    }

    return `
        <section class="memory-page-block memory-source-block">
            <div class="memory-block-title">${escapeHtml(t_js('memory_section_sources'))}</div>
            <div class="memory-source-list">
                ${normalized.map(renderMemorySourceCard).join('')}
            </div>
        </section>
    `;
}

function renderMemorySourceCard(source) {
    const icon = getMemoryItemIcon(source.itemType);
    const typeLabel = formatMemoryItemType(source.itemType);
    const subtitle = source.subtitle ? `<div class="memory-source-subtitle">${escapeHtml(source.subtitle)}</div>` : '';
    const preview = source.preview ? `<div class="memory-source-preview">${renderRichMemoryText(source.preview)}</div>` : '';
    const action = source.href
        ? `<a class="memory-source-action" href="${escapeHtml(source.href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(t_js('memory_source_open'))}</a>`
        : '';

    return `
        <div class="memory-source-card">
            <div class="memory-source-icon" aria-hidden="true">
                <i class="${escapeHtml(icon)}"></i>
            </div>
            <div class="memory-source-copy">
                <div class="memory-source-kicker">${escapeHtml(typeLabel)}</div>
                <div class="memory-source-title">${escapeHtml(source.title)}</div>
                ${subtitle}
                ${preview}
            </div>
            ${action}
        </div>
    `;
}

function renderMemoryMeta(presentation) {
    const parts = [];
    if (presentation.sourceCountLabel) {
        parts.push(`<span class="memory-inline-meta-copy">${escapeHtml(presentation.sourceCountLabel)}</span>`);
    }
    if (presentation.updatedLabel) {
        parts.push(`<span class="memory-inline-meta-copy memory-inline-meta-updated">${escapeHtml(presentation.updatedLabel)}</span>`);
    }
    return parts.join('');
}

function buildMemoryPresentation(page) {
    const rawSourceItems = normalizeMemorySourceItems(page.source_items || []);
    const title = chooseMemoryDisplayTitle(page, rawSourceItems);
    const titleExcludes = [title, page.title];

    let heroText = cleanMemoryText(page.summary, titleExcludes);
    let keyPoints = cleanMemoryEntries(page.key_points || [], [title, page.title, heroText]);
    if (!heroText && keyPoints.length === 1) {
        heroText = keyPoints[0];
        keyPoints = [];
    }

    const decisions = cleanMemoryEntries(page.decisions || [], [title, heroText, ...keyPoints]);
    const openQuestions = cleanMemoryEntries(page.open_questions || [], [title, heroText, ...keyPoints, ...decisions]);
    const nextSteps = cleanMemoryEntries(page.next_steps || [], [title, heroText, ...keyPoints, ...decisions, ...openQuestions]);

    const sources = buildMemorySources({
        title,
        heroText,
        keyPoints,
        decisions,
        openQuestions,
        nextSteps,
        sourceItems: rawSourceItems,
        sourceStrings: page.sources || [],
    });

    return {
        title,
        heroText,
        keyPoints,
        decisions,
        openQuestions,
        nextSteps,
        sources,
        sourceCountLabel: formatMemorySourceCount(sources.length || rawSourceItems.length || 0),
        updatedLabel: page.last_updated_at ? `${t_js('memory_updated_at')} ${formatMemoryDate(page.last_updated_at)}` : '',
    };
}

function chooseMemoryDisplayTitle(page, sourceItems) {
    const fallbackTitle = String(page.title || '').trim() || t_js('memory_untitled');
    if (!looksLikeUrl(fallbackTitle)) {
        return fallbackTitle;
    }

    const sourceTitle = sourceItems.find(item => item.title && !looksLikeUrl(item.title))?.title;
    if (sourceTitle) {
        return sourceTitle;
    }

    const summaryTitle = cleanMemoryText(page.summary, [fallbackTitle]);
    return summaryTitle || fallbackTitle;
}

function buildMemorySources({ title, heroText, keyPoints, decisions, openQuestions, nextSteps, sourceItems, sourceStrings }) {
    const excludes = [title, heroText, ...keyPoints, ...decisions, ...openQuestions, ...nextSteps];
    const normalized = [];
    const hasStructuredSources = Boolean((sourceItems || []).length);

    sourceItems.forEach(item => {
        const titleText = cleanMemoryText(item.title || item.filename || item.source_url || '', excludes);
        const previewText = cleanMemoryText(item.content_preview, [title, heroText, titleText, ...excludes]);
        const subtitle = buildMemorySourceSubtitle(item, titleText);
        const href = item.access_url || item.source_url || '';

        if (!href && !titleText && !previewText) {
            return;
        }

        const source = {
            itemType: item.item_type || item.itemType || 'note',
            title: titleText || item.filename || item.source_url || formatMemoryItemType(item.item_type),
            subtitle,
            preview: previewText,
            href,
        };

        const signature = normalizeMemoryText(`${source.title}|${source.subtitle}|${source.href}`);
        if (signature && !normalized.some(entry => entry.signature === signature)) {
            normalized.push({ ...source, signature });
        }
    });

    if (!hasStructuredSources) {
        sourceStrings.forEach(value => {
        const text = cleanMemoryText(value, excludes);
        if (!text) {
            return;
        }
        const href = looksLikeUrl(text) ? text : '';
        const titleText = href ? stripProtocol(text) : text;
        const signature = normalizeMemoryText(`${titleText}|${href}`);
        if (signature && !normalized.some(entry => entry.signature === signature)) {
            normalized.push({
                itemType: href ? 'link' : 'note',
                title: titleText,
                subtitle: href ? memoryDomain(href) : '',
                preview: '',
                href,
                signature,
            });
        }
        });
    }

    const nonRedundant = normalized.filter(source => {
        const sourceText = normalizeMemoryText([source.title, source.subtitle, source.preview].join(' '));
        return source.href || !excludes.some(entry => isSameMemoryText(sourceText, entry));
    });

    if (nonRedundant.length === 1 && !nonRedundant[0].href && !heroText && !keyPoints.length && !decisions.length && !openQuestions.length && !nextSteps.length) {
        return [];
    }

    return nonRedundant.map(({ signature, ...rest }) => rest);
}

function normalizeMemorySourceItems(sourceItems) {
    return sourceItems
        .filter(Boolean)
        .map(item => ({
            itemType: item.item_type || item.itemType || 'note',
            title: String(item.title || '').trim(),
            content_preview: String(item.content_preview || '').trim(),
            source_url: String(item.source_url || '').trim(),
            filename: String(item.filename || '').trim(),
            access_url: String(item.access_url || '').trim(),
        }));
}

function buildMemorySourceSubtitle(item, titleText) {
    if (item.source_url) {
        const domain = memoryDomain(item.source_url);
        if (domain && !isSameMemoryText(domain, titleText)) {
            return domain;
        }
    }
    if (item.filename && !isSameMemoryText(item.filename, titleText)) {
        return item.filename;
    }
    return '';
}

function cleanMemoryEntries(entries, excludes) {
    const normalized = [];
    (entries || []).forEach(entry => {
        const text = cleanMemoryText(entry, excludes);
        if (!text) {
            return;
        }
        if (!normalized.some(candidate => isSameMemoryText(candidate, text))) {
            normalized.push(text);
        }
    });
    return normalized;
}

function cleanMemoryText(value, excludes = []) {
    const text = String(value || '').trim();
    if (!text) {
        return '';
    }
    if (String(text).toLowerCase() === String(t_js('memory_no_summary')).toLowerCase()) {
        return '';
    }
    if (excludes.some(entry => isSameMemoryText(entry, text))) {
        return '';
    }
    return text;
}

function formatMemorySourceCount(count) {
    if (!count) {
        return '';
    }
    if (count === 1) {
        return t_js('memory_source_count_one');
    }
    return t_js('memory_source_count_many').replace('{count}', String(count));
}

function looksLikeUrl(value) {
    return /^https?:\/\//i.test(String(value || '').trim());
}

function memoryDomain(value) {
    try {
        return new URL(value).hostname.replace(/^www\./i, '');
    } catch (error) {
        return '';
    }
}

function stripProtocol(value) {
    return String(value || '').replace(/^https?:\/\//i, '').replace(/\/$/, '');
}

function normalizeMemoryText(value) {
    return String(value || '')
        .toLowerCase()
        .normalize('NFKD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/https?:\/\//g, '')
        .replace(/[^\w\s]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

function isSameMemoryText(left, right) {
    const normalizedLeft = normalizeMemoryText(left);
    const normalizedRight = normalizeMemoryText(right);
    if (!normalizedLeft || !normalizedRight) {
        return false;
    }
    return normalizedLeft === normalizedRight;
}

function formatMemoryItemType(itemType) {
    const mapping = {
        chat_user_message: t_js('memory_item_chat_user_message'),
        chat_assistant_message: t_js('memory_item_chat_assistant_message'),
        note: t_js('memory_item_note'),
        link: t_js('memory_item_link'),
        file: t_js('memory_item_file'),
        image: t_js('memory_item_image')
    };
    return mapping[itemType] || itemType || t_js('memory_item_default');
}

function buildMemoryCapturePreview(item, preview) {
    const normalizedPreview = String(preview || '').trim();
    if (item.item_type === 'link' && item.source_url) {
        return normalizedPreview || stripProtocol(item.source_url);
    }
    if ((item.item_type === 'file' || item.item_type === 'image') && item.filename) {
        return item.filename;
    }
    return normalizedPreview;
}

function normalizeCaptureList(captures) {
    return (captures || []).map(capture => {
        if (capture && Array.isArray(capture.items)) {
            return {
                ...capture,
                items: [...capture.items].sort((left, right) => new Date(right.created_at || 0).getTime() - new Date(left.created_at || 0).getTime()),
                primaryItem: choosePrimaryCaptureItem(capture.items || []),
            };
        }
        return {
            capture_id: capture.capture_id || capture.id,
            title: capture.title || '',
            created_at: capture.created_at || null,
            items: [capture],
            primaryItem: capture,
        };
    });
}

function choosePrimaryCaptureItem(items) {
    const order = ['note', 'chat_user_message', 'chat_assistant_message', 'link', 'image', 'file'];
    for (const itemType of order) {
        const match = items.find(item => item.item_type === itemType);
        if (match) {
            return match;
        }
    }
    return items[0];
}

function buildCapturePreview(group) {
    const primary = group.primaryItem || choosePrimaryCaptureItem(group.items || []) || {};
    const preview = primary.content_preview || primary.title || primary.filename || primary.source_url || '';
    return buildMemoryCapturePreview(primary, preview);
}

function buildCaptureResources(group) {
    const resources = [];
    group.items.forEach(item => {
        const href = item.access_url || item.source_url || '';
        if (!href) {
            return;
        }
        const label = item.item_type === 'link'
            ? stripProtocol(item.source_url || '')
            : (item.filename || item.title || t_js('memory_capture_open_resource'));
        const signature = `${item.item_type}|${label}|${href}`;
        if (!resources.some(resource => resource.signature === signature)) {
            resources.push({ signature, href, label });
        }
    });
    return resources.map(({ signature, ...rest }) => rest);
}

function renderCaptureResources(container, resources) {
    if (!resources.length) {
        container.remove();
        return;
    }
    resources.forEach(resource => {
        const link = $(`<a class="memory-item-resource-link" target="_blank" rel="noopener noreferrer"></a>`);
        link.attr('href', resource.href).text(resource.label);
        container.append(link);
    });
}

function getMemoryCaptureIcon(group) {
    if ((group.items || []).length > 1) {
        return 'bi bi-collection';
    }
    return getMemoryItemIcon(group.primaryItem?.item_type);
}

function formatMemoryCaptureTimestamp(value) {
    if (!value) {
        return '';
    }
    try {
        return new Intl.DateTimeFormat(undefined, {
            dateStyle: 'medium',
            timeStyle: 'short',
        }).format(new Date(value));
    } catch (error) {
        return formatMemoryDate(value);
    }
}

function chooseEditableTextItem(items) {
    return (items || []).find(item => ['note', 'link', 'chat_user_message', 'chat_assistant_message'].includes(item.item_type));
}

async function collectCaptureDraft() {
    const rawText = ($('#memory-capture-input').val() || '').trim();
    const pond = window.memoryFilePond;
    const nativeInput = document.getElementById('memory-file-input');
    const files = pond
        ? pond.getFiles()
        : Array.from((nativeInput && nativeInput.files) || []).map(file => ({ file }));
    const urls = extractUrls(rawText);
    const textWithoutUrls = rawText.replace(URL_EXTRACT_REGEX, ' ').replace(/\s+/g, ' ').trim();
    const hasText = Boolean(rawText);
    const hasFiles = Boolean(files.length);

    const editableTextItems = memoryEditingCapture ? getEditableTextItems(memoryEditingCapture.items || []) : [];
    const originalText = memoryEditingCapture ? buildEditableCaptureText(memoryEditingCapture.items || []) : '';
    const keepItemIds = new Set(
        ((memoryEditingCapture && memoryEditingCapture.items) || [])
            .filter(item => !memoryEditingRemovedItemIds.has(item.id))
            .map(item => item.id)
    );

    const newItems = [];
    const shouldSaveLinkCapture = urls.length === 1 && !textWithoutUrls;

    if (memoryEditingCapture && editableTextItems.length) {
        const textChanged = rawText !== originalText;
        const textCleared = !hasText;
        if (textChanged || textCleared) {
            editableTextItems.forEach(item => keepItemIds.delete(item.id));
        }
    }

    const textChanged = !memoryEditingCapture || rawText !== originalText;
    if (shouldSaveLinkCapture) {
        if (textChanged) {
            urls.forEach(url => {
                newItems.push({
                    item_type: 'link',
                    source_url: url,
                    title: url,
                });
            });
        }
    } else if (hasText) {
        if (textChanged) {
            if (textWithoutUrls) {
                newItems.push({
                    item_type: 'note',
                    content_text: textWithoutUrls,
                    title: textWithoutUrls.slice(0, 120),
                });
            }
            dedupeUrls(urls).forEach(url => {
                newItems.push({
                    item_type: 'link',
                    source_url: url,
                    title: url,
                });
            });
        } else if (!textWithoutUrls && !urls.length && editableTextItems.length) {
            newItems.push({
                item_type: 'note',
                content_text: rawText,
                title: rawText.slice(0, 120),
            });
        }
    }

    for (const fileItem of files) {
        const file = fileItem.file;
        if (!file) {
            continue;
        }
        const encoded = await fileToBase64(file);
        newItems.push({
            item_type: (file.type || '').startsWith('image/') ? 'image' : 'file',
            filename: file.name,
            mime_type: file.type,
            file_base64: encoded,
            title: file.name,
        });
    }

    if (!hasText && !hasFiles && !keepItemIds.size) {
        return null;
    }

    return {
        captureText: rawText,
        title: textWithoutUrls || rawText.slice(0, 120),
        newItems,
        keepItemIds: Array.from(keepItemIds),
    };
}

function getMemoryItemIcon(itemType) {
    const mapping = {
        chat_user_message: 'bi bi-chat-left-text',
        chat_assistant_message: 'bi bi-chat-square-quote',
        note: 'bi bi-journal-text',
        link: 'bi bi-link-45deg',
        file: 'bi bi-file-earmark-text',
        image: 'bi bi-image'
    };
    return mapping[itemType] || 'bi bi-bookmark';
}

function getEditableTextItems(items) {
    return (items || []).filter(item => ['note', 'link', 'chat_user_message', 'chat_assistant_message'].includes(item.item_type));
}

function isTextareaManagedCaptureItem(item) {
    return ['note', 'link', 'chat_user_message', 'chat_assistant_message'].includes(item?.item_type);
}

function buildEditableCaptureText(items) {
    const textItems = getEditableTextItems(items);
    const noteLike = textItems.find(item => ['note', 'chat_user_message', 'chat_assistant_message'].includes(item.item_type));
    const baseText = String(noteLike?.content_text || noteLike?.title || '').trim();
    const urls = dedupeUrls(
        textItems
            .filter(item => item.item_type === 'link')
            .map(item => String(item.source_url || item.title || '').trim())
            .filter(Boolean)
    ).filter(url => !baseText.includes(url));

    if (baseText && urls.length) {
        return `${baseText} ${urls.join(' ')}`.trim();
    }
    if (baseText) {
        return baseText;
    }
    return urls.join(' ').trim();
}

function dedupeUrls(urls) {
    return Array.from(new Set((urls || []).map(url => String(url || '').trim()).filter(Boolean)));
}

function formatMemoryDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString();
}

function escapeHtml(value) {
    return $('<div>').text(value).html();
}

function renderRichMemoryText(value) {
    return escapeHtml(String(value || '')).replace(
        /(https?:\/\/[^\s<]+)/gi,
        (url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`
    );
}

function fileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            const result = String(reader.result || '');
            resolve(result.includes(',') ? result.split(',')[1] : result);
        };
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

function nextPaint() {
    return new Promise(resolve => {
        window.requestAnimationFrame(() => resolve());
    });
}

const URL_EXTRACT_REGEX = /https?:\/\/[^\s]+/gi;

function extractUrls(value) {
    return Array.from(String(value || '').match(URL_EXTRACT_REGEX) || [])
        .map(url => url.trim())
        .filter(Boolean);
}

window.saveItemToMemory = saveItemToMemory;
window.refreshMemoryDashboard = refreshMemoryDashboard;
