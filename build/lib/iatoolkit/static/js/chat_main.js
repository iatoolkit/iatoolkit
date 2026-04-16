// Global variables for request management
let isRequestInProgress = false;
let abortController = null;
let selectedPrompt = null; // Will hold a lightweight prompt object

$(document).ready(function () {
    // Si viene un Token retornado por login con APY-KEY se gatilla el redeem a una sesion de flask
        if (window.redeemToken) {
            const url = '/api/redeem_token';
            // No await: dejamos que callToolkit maneje todo internamente
            callToolkit(url, {'token': window.redeemToken}, "POST").catch(() => {});
        }

    const layoutContainer = document.querySelector('.chat-layout-container');
    const promptAssistantCollapse = document.getElementById('prompt-assistant-collapse');

    if (layoutContainer && promptAssistantCollapse) {
        promptAssistantCollapse.addEventListener('show.bs.collapse', function () {
            layoutContainer.classList.add('prompt-assistant-open');
            setTimeout(() => {
                window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
            }, 300);
        });

        promptAssistantCollapse.addEventListener('hide.bs.collapse', function () {
            layoutContainer.classList.remove('prompt-assistant-open');
        });
    }

    // --- chat main event hadlers ---
    $('#send-button').on('click', handleChatMessage);
    $('#stop-button').on('click', abortCurrentRequest);
    if (window.sendButtonColor)
        $('#send-button i').css('color', window.sendButtonColor);


    // Handles Enter key press to send a message
    const questionTextarea = $('#question');
    questionTextarea.on('keypress', function (event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            handleChatMessage();
        }
    });

    // Handles auto-resizing and enables the send button on input
    questionTextarea.on('input', function () {
        autoResizeTextarea(this);
        // If the user types, it overrides any prompt selection
        if (selectedPrompt) {
            resetPromptSelection();
        }
        updateSendButtonState();
    });

    // Set the initial disabled state of the send button
    updateSendButtonState();

});

/**
 * Main function to handle sending a chat message.
 */
const handleChatMessage = async function () {
    if (isRequestInProgress || $('#send-button').hasClass('disabled')) {
        return;
    }

    isRequestInProgress = true;
    toggleSendStopButtons(true);

    try {
        const question = $('#question').val().trim();
        const promptName = selectedPrompt ? selectedPrompt.prompt : null;

        let displayMessage = question;
        let isEditable = true;
        const clientData = {};

        if (selectedPrompt) {
            displayMessage = selectedPrompt.description;
            isEditable = false;

            (selectedPrompt.custom_fields || []).forEach(field => {
                const value = $('#' + field.data_key + '-id').val().trim();
                if (value) {
                    clientData[field.data_key] = value;
                }
            });

            const paramsString = Object.values(clientData).join(', ');
            if (paramsString) { displayMessage += `: ${paramsString}`; }
        }

        if (!displayMessage) {
            return;
        }

        const files = window.filePond.getFiles();

        displayUserMessage(displayMessage, isEditable, question, files);
        showSpinner();
        resetAllInputs();

        const filesBase64 = await Promise.all(files.map(fileItem => toBase64(fileItem.file)));

        const data = {
            question: question,
            prompt_name: promptName,
            client_data: clientData,
            files: filesBase64.map(f => ({ filename: f.name, content: f.base64 })),
            user_identifier: window.user_identifier,
            model: (window.currentLlmModel || window.defaultLlmModel || '')
        };

        const responseData = await callToolkit("/api/llm_query", data, "POST");

        // Delegamos el procesamiento de la respuesta a la nueva función
        processBotResponse(responseData);

    } catch (error) {
        if (error.name === 'AbortError') {
            const icon = $('<i>').addClass('bi bi-stop-circle me-2');
            const textSpan = $('<span>').text('La generación de la respuesta ha sido detenida.');
            const abortMessage = $('<div>').addClass('system-message').append(icon).append(textSpan);
            displayBotMessage(abortMessage);
        } else {
            console.error("Error in handleChatMessage:", error);
            const errorSection = $('<div>').addClass('error-section').append('<p>Ocurrió un error al procesar la solicitud.</p>');
            displayBotMessage(errorSection);
        }
    } finally {
        isRequestInProgress = false;
        hideSpinner();
        toggleSendStopButtons(false);
        updateSendButtonState();
        if (window.filePond) {
            window.filePond.removeFiles();
        }
    }
};

/**
 * Processes the response data from the LLM and displays it in the chat.
 * Handles multimodal content: uses 'answer' for text (HTML) and 'content_parts' for images.
 * @param {object} responseData - The JSON response from the server.
 */
function processBotResponse(responseData) {
    if (!responseData || (!responseData.answer && !responseData.content_parts)) {
        return;
    }

    const botMessageContainer = $('<div>').addClass('bot-message-container');

    // 1. Si hay reasoning_content, agregar el acordeón colapsable
    if (responseData.reasoning_content) {
        const uniqueId = 'reasoning-' + Date.now();
        const reasoningBlock = $(`
                <div class="reasoning-block">
                    <button class="reasoning-toggle btn btn-sm btn-link text-decoration-none p-0"
                        type="button" data-bs-toggle="collapse" data-bs-target="#${uniqueId}"
                        aria-expanded="false" aria-controls="${uniqueId}">
                        <i class="bi bi-lightbulb me-1"></i> ${t_js('show_reasoning')}
                    </button>
                    <div class="collapse mt-2" id="${uniqueId}">
                        <div class="reasoning-card">${responseData.reasoning_content}</div>
                    </div>
                </div>
            `);
        botMessageContainer.append(reasoningBlock);
    }

    // 2. Agregar la respuesta final
    const answerSection = $('<div>').addClass('answer-section llm-output');

    // A. Texto: Usamos 'answer' porque contiene el HTML procesado y limpio del backend.
    // Evitamos usar content_parts[type=text] porque contiene el JSON crudo del LLM.
    if (responseData.answer) {
        answerSection.append(responseData.answer);
    }

    // B. Imágenes: Iteramos content_parts buscando SOLO imágenes para adjuntarlas.
    if (responseData.content_parts && responseData.content_parts.length > 0) {
        responseData.content_parts.forEach(part => {
            if (part.type === 'image' && part.source && part.source.url) {
                const imgContainer = $('<div>').addClass('image-part my-3 text-center');
                const img = $('<img>')
                    .attr('src', part.source.url)
                    .addClass('img-fluid rounded shadow-sm border')
                    .css({'max-height': '400px', 'cursor': 'pointer'})
                    .on('click', () => window.open(part.source.url, '_blank'));

                imgContainer.append(img);
                answerSection.append(imgContainer);
            }
        });
    }

    botMessageContainer.append(answerSection);

    // 3. Mostrar el contenedor completo
    displayBotMessage(botMessageContainer);
}


/**
 * Resets all inputs to their initial state.
 */
function resetAllInputs() {
    resetPromptSelection();
    $('#question').val('');
    autoResizeTextarea($('#question')[0]);

    const promptCollapseEl = document.getElementById('prompt-assistant-collapse');
    const promptCollapse = bootstrap.Collapse.getInstance(promptCollapseEl);
    if (promptCollapse) {
        promptCollapse.hide();
    }

    updateSendButtonState();
}

/**
 * Enables or disables the send button based on whether there's content
 * in the textarea or a prompt has been selected.
 */
function updateSendButtonState() {
    const question = $('#question').val().trim();
    const isPromptSelected = selectedPrompt !== null;

    if (isPromptSelected || question) {
        $('#send-button').removeClass('disabled');
    } else {
        $('#send-button').addClass('disabled');
    }
}

/**
 * Auto-resizes the textarea to fit its content.
 */
function autoResizeTextarea(element) {
    element.style.height = 'auto';
    element.style.height = (element.scrollHeight) + 'px';
}

/**
 * Toggles the main action button between 'Send' and 'Stop'.
 * @param {boolean} showStop - If true, shows the Stop button. Otherwise, shows the Send button.
 */
const toggleSendStopButtons = function (showStop) {
    $('#send-button-container').toggle(!showStop);
    $('#stop-button-container').toggle(showStop);
};

/**
 * Generic function to make API calls to the backend.
 * @param {string} apiPath - The API endpoint path.
 * @param {object} data - The data payload to send.
 * @param {string} method - The HTTP method (e.g., 'POST').
 * @param {number} timeoutMs - Timeout in milliseconds.
 * @returns {Promise<object|null>} The response data or null on error.
 */
const callToolkit = async function(apiPath, data, method, timeoutMs = 500000) {
    // normalize the url for avoiding double //
    const base = (window.iatoolkit_base_url || '').replace(/\/+$/, '');
    const company = (window.companyShortName || '').replace(/^\/+|\/+$/g, '');
    const path = apiPath.startsWith('/') ? apiPath : `/${apiPath}`;
    const url = `${base}/${company}${path}`;


    abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), timeoutMs);

    try {
        const fetchOptions = {
                method: method,
                signal: abortController.signal,
                credentials: 'include'
            };

        // Solo agrega body si el método lo soporta y hay datos
        const methodUpper = (method || '').toUpperCase();
        const canHaveBody = !['GET', 'HEAD'].includes(methodUpper);
        if (canHaveBody && data !== undefined && data !== null) {
            fetchOptions.body = JSON.stringify(data);
            fetchOptions.headers = {"Content-Type": "application/json"};

        }
        const response = await fetch(url, fetchOptions);
        clearTimeout(timeoutId);

        // answer is NOT OK (status != 200)
        if (!response.ok) {
            try {
                // Intentamos leer el error como JSON, que es el formato esperado de nuestra API.
                const errorData = await response.json();

                // if it's a iatoolkit error  (409 o 400 with a message), shot it on the chat
                if (errorData && (errorData.error_message || errorData.error)) {
                    const errorMessage = errorData.error_message || errorData.error || t_js('unknown_server_error');
                    const errorIcon = '<i class="bi bi-exclamation-triangle"></i>';
                    const endpointError = $('<div>').addClass('error-section').html(errorIcon + `<p>${errorMessage}</p>`);
                    displayBotMessage(endpointError);
                } else {
                    // if there is not message, we show a generic error message
                    throw new Error(`Server error: ${response.status}`);
                }
            } catch (e) {
                // Si response.json() falla, es porque el cuerpo no era JSON (ej. un 502 con HTML).
                // Mostramos un error genérico y más claro para el usuario.
                const errorMessage = `Error de comunicación con el servidor (${response.status}). Por favor, intente de nuevo más tarde.`;
                toastr.error(errorMessage);
            }

            // stop the flow on the calling function
            return null;
        }

        // if the answer is OK
        return await response.json();
    } catch (error) {
        clearTimeout(timeoutId);
        if (error.name === 'AbortError') {
            throw error; // Re-throw to be handled by handleChatMessage
        } else {
            toastr.error(t_js('network_error') );
        }
        return null;
    }
};


/**
 * Displays the user's message in the chat container.
 * @param {string} message - The full message string to display.
 * @param {boolean} isEditable - Determines if the edit icon should be shown.
 * @param {string} originalQuestion - The original text to put back in the textarea for editing.
 * @param {Array} [files] - Optional array of FilePond file items.
 */
const displayUserMessage = function(message, isEditable, originalQuestion, files = []) {
    const chatContainer = $('#chat-container');
    const userMessage = $('<div>').addClass('message shadow-sm');
    const messageText = $('<span>').text(message);

    userMessage.append(messageText);

    // Renderizar previsualizaciones de archivos si existen
    if (files && files.length > 0) {
        const attachmentsContainer = $('<div>').addClass('mt-2 d-flex flex-wrap gap-2 ms-3');

        files.forEach(fileItem => {
            const file = fileItem.file;

            if (file.type && file.type.startsWith('image/')) {
                // Previsualización de imagen usando URL temporal
                const imgUrl = URL.createObjectURL(file);
                const img = $('<img>')
                    .attr('src', imgUrl)
                    .addClass('rounded border')
                    .css({
                        'max-height': '80px',
                        'max-width': '120px',
                        'object-fit': 'cover',
                        'cursor': 'pointer'
                    })
                    .on('click', () => window.open(imgUrl, '_blank')); // Click para ver en grande
                attachmentsContainer.append(img);
            } else {
                // Icono genérico para documentos
                const badge = $('<span>')
                    .addClass('badge bg-light text-dark border p-2')
                    .html(`<i class="bi bi-file-earmark-text me-1"></i> ${file.name}`);
                attachmentsContainer.append(badge);
            }
        });

        userMessage.append(attachmentsContainer);
    }

    if (isEditable) {
        const editIcon = $('<i>').addClass('p-2 bi bi-pencil-fill edit-icon edit-pencil').attr('title', 'Edit query').on('click', function () {
            $('#question').val(originalQuestion)
            autoResizeTextarea($('#question')[0]);
            $('#send-button').removeClass('disabled');

            if (window.innerWidth > 768)
                $('#question').focus();
        });
        userMessage.append(editIcon);
    }
    chatContainer.append(userMessage);
    chatContainer.scrollTop(chatContainer[0].scrollHeight);
};

/**
 * Appends a message from the bot to the chat container.
 * @param {jQuery} section - The jQuery object to append.
 */
function displayBotMessage(section) {
    const chatContainer = $('#chat-container');
    chatContainer.append(section);
    chatContainer.scrollTop(chatContainer[0].scrollHeight);
}

/**
 * Aborts the current in-progress API request.
 */
const abortCurrentRequest = function () {
    if (isRequestInProgress && abortController) {
        abortController.abort();
    }
};

/**
 * Shows the loading spinner in the chat.
 */
const showSpinner = function () {
    if ($('#spinner').length) return;
    const accessibilityClass = (typeof bootstrap !== 'undefined') ? 'visually-hidden' : 'sr-only';
    const spinnerText = t_js('loading');
    const spinner = $(`
        <div id="spinner" style="display: flex; align-items: center; justify-content: start; margin: 10px 0; padding: 10px;">
            <div class="spinner-border" role="status" style="width: 1.5rem; height: 1.5rem; margin-right: 15px;">
                <span class="${accessibilityClass}">Loading...</span>
            </div>
            <span style="font-weight: bold; font-size: 15px;">${spinnerText}</span>
        </div>
    `);
    $('#chat-container').append(spinner).scrollTop($('#chat-container')[0].scrollHeight);
};

/**
 * Hides the loading spinner.
 */
function hideSpinner() {
    $('#spinner').fadeOut(function () {
        $(this).remove();
    });
}

/**
 * Converts a File object to a Base64 encoded string.
 * @param {File} file The file to convert.
 * @returns {Promise<{name: string, base64: string}>}
 */
function toBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve({name: file.name, base64: reader.result.split(",")[1]});
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

