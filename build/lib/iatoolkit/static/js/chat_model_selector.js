// src/iatoolkit/static/js/chat_model_selector.js
// Gestión del selector de modelo LLM en la barra superior.

// Estado global del modelo actual (visible también para otros scripts)
window.currentLlmModel = window.currentLlmModel || null;

(function () {
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
            description: m.description || ''
        })).filter(m => !!m.id);
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

    /**
     * Pinta la lista de modelos en el popup y marca el seleccionado.
     */
    function renderModelList() {
        const listEl = document.getElementById('llm-model-list');
        if (!listEl) return;

        const models = getAvailableModels();
        const activeId = window.currentLlmModel;
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

    /**
     * Selecciona un modelo: actualiza estado global, UI y almacenamiento local.
     */
    function selectModel(modelId) {
        if (!modelId) return;

        const models = getAvailableModels();
        const exists = models.some(m => m.id === modelId);
        if (!exists) return;

        window.currentLlmModel = modelId;
        storeModelId(modelId);
        updateButtonLabel();
        renderModelList();
        hidePopup();

        if (typeof toastr !== 'undefined') {
            toastr.info(`Modelo actualizado a "${models.find(m => m.id === modelId).label}".`);
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
            const rect = btn.getBoundingClientRect();
            popup.style.display = 'block';

            // Posicionamos justo debajo del botón, alineado a la izquierda
            popup.style.top = `${rect.bottom + window.scrollY + 4}px`;
            popup.style.left = `${rect.left + window.scrollX}px`;
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
        updateButtonLabel();
        renderModelList();
        setupOutsideClickHandler();

        const btn = document.getElementById('llm-model-button');
        if (btn) {
            btn.addEventListener('click', (event) => {
                event.stopPropagation();
                togglePopup();
            });
        }
    });
})();