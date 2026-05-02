// src/iatoolkit/static/js/chat_model_selector.js
// Gestión del selector de modelo LLM en la barra superior.

// Estado global del modelo actual (visible también para otros scripts)
window.currentLlmModel = window.currentLlmModel || null;
window.currentLlmReasoningEffort = window.currentLlmReasoningEffort || null;

(function () {
    let pendingLlmModel = null;
    let pendingReasoningEffort = null;

    function t(key, fallback) {
        if (typeof window.t_js === 'function') {
            const value = window.t_js(key);
            if (value && value !== key) return value;
        }
        return fallback;
    }

    /**
     * Lee el modelo guardado en localStorage (si existe y es válido).
     */
    function loadStoredModelId() {
        try {
            const stored = localStorage.getItem('iatoolkit.selected_llm_model');
            return stored || null;
        } catch (e) {
            return null;
        }
    }

    /**
     * Guarda el modelo seleccionado en localStorage para esta instancia de navegador.
     * No es crítico: si falla, simplemente no persistimos.
     */
    function storeModelId(modelId) {
        try {
            if (!modelId) {
                localStorage.removeItem('iatoolkit.selected_llm_model');
            } else {
                localStorage.setItem('iatoolkit.selected_llm_model', modelId);
            }
        } catch (e) {
            // No hacemos nada: fallo silencioso
        }
    }

    /**
     * Devuelve la lista de modelos disponibles desde la variable global.
     */
    function getAvailableModels() {
        const raw = window.availableLlmModels;
        if (!Array.isArray(raw)) {
            return [];
        }
        return raw.map(m => ({
            id: m.id,
            label: m.label || m.id,
            description: m.description || '',
            provider: m.provider || '',
            supportsReasoningEffort: inferReasoningSupport({
                id: m.id,
                provider: m.provider || '',
                supportsReasoningEffort: typeof m.supports_reasoning_effort === 'boolean'
                    ? m.supports_reasoning_effort
                    : undefined,
            }),
            allowedReasoningEfforts: Array.isArray(m.allowed_reasoning_efforts)
                ? m.allowed_reasoning_efforts.map(value => String(value || '').trim().toLowerCase()).filter(Boolean)
                : []
        })).filter(m => !!m.id);
    }

    function getReasoningOptions() {
        return [
            { id: 'minimal', label: t('ui.prompts.thinking_level_minimal', 'Minimal') },
            { id: 'low', label: t('ui.prompts.thinking_level_low', 'Low') },
            { id: 'medium', label: t('ui.prompts.thinking_level_medium', 'Medium') },
            { id: 'high', label: t('ui.prompts.thinking_level_high', 'High') },
            { id: 'xhigh', label: t('ui.prompts.thinking_level_xhigh', 'XHigh') },
        ];
    }

    function inferReasoningSupport(model) {
        if (typeof model?.supportsReasoningEffort === 'boolean') {
            return model.supportsReasoningEffort;
        }

        const provider = String(model?.provider || '').trim().toLowerCase();
        const normalizedModelId = String(model?.id || '').trim().toLowerCase();
        const inferredProvider = provider
            || (
                normalizedModelId.includes('deepseek') ? 'deepseek'
                : normalizedModelId.startsWith('gpt-') || normalizedModelId.startsWith('o1') || normalizedModelId.startsWith('o3') || normalizedModelId.startsWith('o4') ? 'openai'
                : normalizedModelId.startsWith('grok-') ? 'xai'
                : normalizedModelId.startsWith('openrouter/') ? 'openrouter'
                : ''
            );

        return ['openai', 'xai', 'openrouter', 'deepseek', 'openai_compatible'].includes(inferredProvider);
    }

    function getActiveModelMetadata() {
        const models = getAvailableModels();
        const modelId = window.currentLlmModel || window.defaultLlmModel || '';
        const model = models.find((item) => item.id === modelId) || null;
        return {
            id: modelId,
            label: model ? model.label : modelId,
            provider: model ? model.provider : '',
            supportsReasoningEffort: model ? model.supportsReasoningEffort : false,
            allowedReasoningEfforts: model ? model.allowedReasoningEfforts : [],
        };
    }

    function modelSupportsReasoning(modelMetadata) {
        return modelMetadata.supportsReasoningEffort === true;
    }

    function getAllowedReasoningEfforts(modelMetadata) {
        const allowed = Array.isArray(modelMetadata.allowedReasoningEfforts)
            ? modelMetadata.allowedReasoningEfforts
            : [];
        return allowed.length > 0
            ? allowed
            : getReasoningOptions().map((item) => item.id);
    }

    /**
     * Inicializa el estado de currentLlmModel usando SIEMPRE la config de company.yaml:
     * 1) defaultLlmModel (company.yaml)
     * 2) si no existe o no está en la lista, usa el primer modelo disponible.
     *
     * No se lee nada de localStorage en este punto: cada apertura de chat
     * arranca desde la configuración de la compañía.
     */
    function initCurrentModel() {
        const models = getAvailableModels();
        const defaultId = (window.defaultLlmModel || '').trim() || null;

        let resolved = null;

        if (defaultId && models.some(m => m.id === defaultId)) {
            resolved = defaultId;
        } else if (models.length > 0) {
            resolved = models[0].id;
        }

        window.currentLlmModel = resolved;
        return resolved;
    }

    function initCurrentReasoningEffort() {
        const candidate = String(window.defaultLlmReasoningEffort || '').trim().toLowerCase();
        const allowed = getAllowedReasoningEfforts(getActiveModelMetadata());
        window.currentLlmReasoningEffort = allowed.includes(candidate) ? candidate : null;
        if (!modelSupportsReasoning(getActiveModelMetadata())) {
            window.currentLlmReasoningEffort = null;
        }
    }

    function syncPendingSelectionFromCurrent() {
        pendingLlmModel = window.currentLlmModel || window.defaultLlmModel || null;
        pendingReasoningEffort = window.currentLlmReasoningEffort || null;
    }

    /**
     * Pinta la lista de modelos en el popup y marca el seleccionado.
     */
    function renderModelList() {
        const listEl = document.getElementById('llm-model-list');
        if (!listEl) return;

        const models = getAvailableModels();
        const activeId = pendingLlmModel || window.currentLlmModel;
        listEl.innerHTML = '';

        if (!models.length) {
            const emptyItem = document.createElement('div');
            emptyItem.className = 'list-group-item small text-muted';
            emptyItem.textContent = 'No hay modelos configurados.';
            listEl.appendChild(emptyItem);
            return;
        }

        models.forEach(model => {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'list-group-item list-group-item-action small';

            const isActive = model.id === activeId;
            if (isActive) {
                item.classList.add('active');
            }

            item.innerHTML = `
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <div class="fw-semibold">${model.label}</div>
                        ${model.description
                ? `<div class="text-muted" style="font-size: 0.8rem;">${model.description}</div>`
                : ''
            }
                    </div>
                    ${isActive ? '<i class="bi bi-check-lg ms-2"></i>' : ''}
                </div>
            `;

            item.addEventListener('click', () => {
                selectModel(model.id);
            });
            item.addEventListener('mousedown', (event) => {
                event.stopPropagation();
            });
            item.addEventListener('click', (event) => {
                event.stopPropagation();
            });
            listEl.appendChild(item);
        });
    }

    /**
     * Actualiza el label del botón principal con el modelo actual.
     */
    function updateButtonLabel() {
        const labelEl = document.getElementById('llm-model-button-label');
        if (!labelEl) return;

        const models = getAvailableModels();
        const activeId = window.currentLlmModel;
        const activeModel = models.find(m => m.id === activeId);

        if (activeModel) {
            labelEl.textContent = activeModel.label;
        } else if (window.defaultLlmModel) {
            labelEl.textContent = window.defaultLlmModel;
        } else {
            labelEl.textContent = 'Modelo IA';
        }
    }

    function renderReasoningControl() {
        const selectEl = document.getElementById('llm-reasoning-select');
        const helpEl = document.getElementById('llm-reasoning-help');
        if (!selectEl) return;

        const metadata = getPendingModelMetadata();
        const supported = modelSupportsReasoning(metadata);
        const options = getReasoningOptions();
        const allowed = getAllowedReasoningEfforts(metadata);

        selectEl.innerHTML = '';

        if (!supported) {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = t('ui.prompts.thinking_level_unavailable', 'Not available for this model');
            selectEl.appendChild(option);
            selectEl.disabled = true;
            pendingReasoningEffort = null;
            if (helpEl) {
                helpEl.textContent = t(
                    'ui.prompts.thinking_level_unavailable_help',
                    'This model/provider does not support configurable reasoning effort.'
                );
            }
            return;
        }

        options
            .filter((item) => allowed.includes(item.id))
            .forEach((item) => {
            const option = document.createElement('option');
            option.value = item.id;
            option.textContent = item.label;
            selectEl.appendChild(option);
        });

        if (!allowed.includes(pendingReasoningEffort)) {
            const defaultCandidate = String(window.defaultLlmReasoningEffort || '').trim().toLowerCase();
            pendingReasoningEffort = allowed.includes(defaultCandidate) ? defaultCandidate : (allowed[0] || null);
        }

        selectEl.value = pendingReasoningEffort;
        selectEl.disabled = false;

        if (helpEl) {
            helpEl.textContent = '';
        }
    }

    function getPendingModelMetadata() {
        const models = getAvailableModels();
        const modelId = pendingLlmModel || window.currentLlmModel || window.defaultLlmModel || '';
        const model = models.find((item) => item.id === modelId) || null;
        return {
            id: modelId,
            label: model ? model.label : modelId,
            provider: model ? model.provider : '',
            supportsReasoningEffort: model ? model.supportsReasoningEffort : false,
            allowedReasoningEfforts: model ? model.allowedReasoningEfforts : [],
        };
    }

    /**
     * Selecciona un modelo: actualiza estado global, UI y almacenamiento local.
     */
    function selectModel(modelId) {
        if (!modelId) return;

        const models = getAvailableModels();
        const exists = models.some(m => m.id === modelId);
        if (!exists) return;

        pendingLlmModel = modelId;
        renderModelList();
        renderReasoningControl();
        window.setTimeout(() => {
            if (pendingLlmModel === modelId) {
                renderReasoningControl();
            }
        }, 0);
    }

    function applySelection() {
        const models = getAvailableModels();
        const activeId = pendingLlmModel || window.currentLlmModel;
        if (!activeId) return;

        window.currentLlmModel = activeId;
        window.currentLlmReasoningEffort = pendingReasoningEffort || null;
        storeModelId(activeId);
        updateButtonLabel();
        renderModelList();
        renderReasoningControl();
        hidePopup();

        if (typeof toastr !== 'undefined') {
            const activeModel = models.find((item) => item.id === activeId);
            toastr.info(`${t('ui.chat.model_selector_updated', 'Model updated to')} "${(activeModel && activeModel.label) || activeId}".`);
        }
    }

    /**
     * Muestra/oculta el popup anclado al botón.
     */
    function togglePopup() {
        const popup = document.getElementById('llm-model-popup');
        const btn = document.getElementById('llm-model-button');
        if (!popup || !btn) return;

        const isVisible = popup.style.display === 'block';

        if (isVisible) {
            hidePopup();
        } else {
            syncPendingSelectionFromCurrent();
            renderModelList();
            renderReasoningControl();
            const rect = btn.getBoundingClientRect();
            popup.style.display = 'block';
            popup.style.top = '0px';
            popup.style.left = '0px';

            const popupRect = popup.getBoundingClientRect();
            const margin = 8;
            const top = Math.min(
                rect.bottom + 4,
                Math.max(margin, window.innerHeight - popupRect.height - margin)
            );
            const left = Math.min(
                rect.left,
                Math.max(margin, window.innerWidth - popupRect.width - margin)
            );

            // El popup usa position: fixed para evitar que lo recorten contenedores con overflow hidden.
            popup.style.top = `${top}px`;
            popup.style.left = `${left}px`;
        }
    }

    function hidePopup() {
        const popup = document.getElementById('llm-model-popup');
        if (popup) {
            popup.style.display = 'none';
        }
    }

    /**
     * Cierra el popup si el usuario hace click fuera.
     */
    function setupOutsideClickHandler() {
        document.addEventListener('click', (event) => {
            const popup = document.getElementById('llm-model-popup');
            const btn = document.getElementById('llm-model-button');
            if (!popup || !btn) return;

            if (popup.style.display !== 'block') return;

            if (!popup.contains(event.target) && !btn.contains(event.target)) {
                hidePopup();
            }
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        // Inicializar estado inicial del modelo
        initCurrentModel();
        initCurrentReasoningEffort();
        syncPendingSelectionFromCurrent();
        updateButtonLabel();
        renderModelList();
        renderReasoningControl();
        setupOutsideClickHandler();

        const btn = document.getElementById('llm-model-button');
        if (btn) {
            btn.addEventListener('click', (event) => {
                event.stopPropagation();
                togglePopup();
            });
        }

        const popup = document.getElementById('llm-model-popup');
        if (popup) {
            popup.addEventListener('click', (event) => {
                event.stopPropagation();
            });
            popup.addEventListener('mousedown', (event) => {
                event.stopPropagation();
            });
        }

        const reasoningSelect = document.getElementById('llm-reasoning-select');
        if (reasoningSelect) {
            reasoningSelect.addEventListener('change', () => {
                const nextValue = String(reasoningSelect.value || '').trim().toLowerCase();
                pendingReasoningEffort = nextValue || null;
            });
        }

        const applyButton = document.getElementById('llm-model-apply-button');
        if (applyButton) {
            applyButton.addEventListener('click', () => {
                applySelection();
            });
            applyButton.addEventListener('mousedown', (event) => {
                event.stopPropagation();
            });
        }

        const cancelButton = document.getElementById('llm-model-cancel-button');
        if (cancelButton) {
            cancelButton.addEventListener('click', () => {
                hidePopup();
            });
            cancelButton.addEventListener('mousedown', (event) => {
                event.stopPropagation();
            });
        }
    });
})();
