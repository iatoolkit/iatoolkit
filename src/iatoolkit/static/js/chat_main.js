// Global variables for request management
let isRequestInProgress = false;
let abortController = null;

let selectedPrompt = null; // Will hold a lightweight prompt object

$(document).ready(function () {
    // --- MAIN EVENT HANDLERS ---
    $('#send-button').on('click', handleChatMessage);
    $('#stop-button').on('click', abortCurrentRequest);
    if (window.sendButtonColor)
        $('#send-button i').css('color', window.sendButtonColor);

// --- PROMPT ASSISTANT FUNCTIONALITY ---
    $('.input-area').on('click', '.dropdown-menu a.dropdown-item', function (event) {
        event.preventDefault();
        const promptData = $(this).data();

        const promptObject = {
            prompt: promptData.promptName,
            description: promptData.promptDescription,
            custom_fields: typeof promptData.customFields === 'string' ? JSON.parse(promptData.customFields) : promptData.customFields
        };

        selectPrompt(promptObject);
    });

    // Handles the 'clear' button for the prompt selector
    $('#clear-selection-button').on('click', function() {
        resetPromptSelection();
        updateSendButtonState();
    });

    // --- TEXTAREA FUNCTIONALITY ---
    const questionTextarea = $('#question');

    // Handles Enter key press to send a message
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
 * Handles the selection of a prompt from the dropdown.
 * @param {object} prompt The prompt object read from data attributes.
 */
function selectPrompt(prompt) {
    selectedPrompt = prompt;

    // Update the dropdown button to show the selected prompt's description
    $('#prompt-select-button').text(prompt.description).addClass('item-selected');
    $('#clear-selection-button').show();

    // Clear the main textarea, as we are now in "prompt mode"
    $('#question').val('');
    autoResizeTextarea($('#question')[0]); // Reset height after clearing

    // Store values in hidden fields for backward compatibility or other uses
    $('#prompt-select-value').val(prompt.prompt);
    $('#prompt-select-description').val(prompt.description);

    // Render the dynamic input fields required by the selected prompt
    renderDynamicInputs(prompt.custom_fields || []);
    updateSendButtonState();
}

/**
 * Resets the prompt selection and clears associated UI elements.
 */
function resetPromptSelection() {
    selectedPrompt = null;

    $('#prompt-select-button').text('Prompts disponibles ....').removeClass('item-selected');
    $('#clear-selection-button').hide();
    $('#prompt-select-value').val('');
    $('#prompt-select-description').val('');

    // Clear any dynamically generated input fields
    $('#dynamic-inputs-container').empty();
}

/**
 * Renders the custom input fields for the selected prompt.
 * @param {Array<object>} fields The array of custom field configurations.
 */
function renderDynamicInputs(fields) {
    const container = $('#dynamic-inputs-container');
    container.empty();

    const row = $('<div class="row g-2"></div>');
    fields.forEach(field => {
        const colDiv = $('<div class="col-md"></div>');
        const formFloating = $('<div class="form-floating"></div>');
        const input = $(`<input type="${field.type || 'text'}" class="form-control form-control-soft" id="${field.data_key}-id" ">`);
        const label = $(`<label for="${field.data_key}-id">${field.label}</label>`);

        formFloating.append(input, label);
        colDiv.append(formFloating);
        row.append(colDiv);
    });

    container.append(row);
}



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

        // Simplificado: Si no hay mensaje, el 'finally' se encargará de limpiar.
        // Simplemente salimos de la función.
        if (!displayMessage) {
            return;
        }

        displayUserMessage(displayMessage, isEditable, question);
        showSpinner();
        resetAllInputs();

        const files = window.filePond.getFiles();
        const filesBase64 = await Promise.all(files.map(fileItem => toBase64(fileItem.file)));

        const data = {
            question: question,
            prompt_name: promptName,
            client_data: clientData,
            files: filesBase64.map(f => ({ filename: f.name, content: f.base64 })),
            user_identifier: window.user_identifier
        };

        const responseData = await callLLMAPI("/llm_query", data, "POST");
        if (responseData && responseData.answer) {
            const answerSection = $('<div>').addClass('answer-section llm-output').append(responseData.answer);
            displayBotMessage(answerSection);
        }
    } catch (error) {
        if (error.name === 'AbortError') {
            console.log('Petición abortada por el usuario.');

            // Usando jQuery estándar para construir el elemento ---
            const icon = $('<i>').addClass('bi bi-stop-circle me-2'); // Icono sin "fill" para un look más ligero
            const textSpan = $('<span>').text('La generación de la respuesta ha sido detenida.');

            const abortMessage = $('<div>')
                .addClass('system-message')
                .append(icon)
                .append(textSpan);

            displayBotMessage(abortMessage);
        } else {
            console.error("Error in handleChatMessage:", error);
            const errorSection = $('<div>').addClass('error-section').append('<p>Ocurrió un error al procesar la solicitud.</p>');
            displayBotMessage(errorSection);
        }
    } finally {
        // Este bloque se ejecuta siempre, garantizando que el estado se limpie.
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
 * Resets the prompt selector to its default state.
 */
function resetPromptSelect() {
    $('#prompt-select-button').text('Prompts disponibles ....').removeClass('item-selected');
    $('#prompt-select-value').val('');
    $('#prompt-select-description').val('');
    $('#clear-selection-button').hide();
}

/**
 * Resets the company-specific data input field.
 */
function resetSpecificDataInput() {
    if (specificDataConfig && specificDataConfig.enabled) {
        const input = $('#' + specificDataConfig.id);
        input.val('').removeClass('has-content');
        $('#clear-' + specificDataConfig.id + '-button').hide();
    }
}


/**
 * Generic function to make API calls to the backend.
 * @param {string} apiPath - The API endpoint path.
 * @param {object} data - The data payload to send.
 * @param {string} method - The HTTP method (e.g., 'POST').
 * @param {number} timeoutMs - Timeout in milliseconds.
 * @returns {Promise<object|null>} The response data or null on error.
 */
const callLLMAPI = async function(apiPath, data, method, timeoutMs = 500000) {
    const url = `${window.iatoolkit_base_url}/${window.companyShortName}${apiPath}`;

    const headers = {"Content-Type": "application/json"};
    if (window.sessionJWT) {
        headers['X-Chat-Token'] = window.sessionJWT;
    }

    abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), timeoutMs);

    try {
        const response = await fetch(url, {
            method: method,
            headers: headers,
            body: JSON.stringify(data),
            signal: abortController.signal, // Se usa el signal del controlador global
            credentials: 'include'
        });
        clearTimeout(timeoutId);

        if (!response.ok) {
            try {
                // Intentamos leer el error como JSON, que es el formato esperado de nuestra API.
                const errorData = await response.json();
                const errorMessage = errorData.error_message || 'Error desconocido del servidor.';
                const errorIcon = '<i class="bi bi-exclamation-triangle"></i>';
                const endpointError = $('<div>').addClass('error-section').html(errorIcon + `<p>${errorMessage}</p>`);
                displayBotMessage(endpointError);
            } catch (e) {
                // Si response.json() falla, es porque el cuerpo no era JSON (ej. un 502 con HTML).
                // Mostramos un error genérico y más claro para el usuario.
                const errorMessage = `Error de comunicación con el servidor (${response.status}). Por favor, intente de nuevo más tarde.`;
                const errorIcon = '<i class="bi bi-exclamation-triangle"></i>';
                const infrastructureError = $('<div>').addClass('error-section').html(errorIcon + `<p>${errorMessage}</p>`);
                displayBotMessage(infrastructureError);
            }
            return null;
        }
        return await response.json();
    } catch (error) {
        clearTimeout(timeoutId);
        if (error.name === 'AbortError') {
            throw error; // Re-throw to be handled by handleChatMessage
        } else {
            const friendlyMessage = "Ocurrió un error de red. Por favor, inténtalo de nuevo en unos momentos.";
            const errorIcon = '<i class="bi bi-exclamation-triangle"></i>';
            const commError = $('<div>').addClass('error-section').html(errorIcon + `<p>${friendlyMessage}</p>`);
            displayBotMessage(commError);
        }
        return null;
    }
};


/**
 * Displays the user's message in the chat container.
 * @param {string} message - The full message string to display.
 * @param {boolean} isEditable - Determines if the edit icon should be shown.
 * @param {string} originalQuestion - The original text to put back in the textarea for editing.
 */
const displayUserMessage = function(message, isEditable, originalQuestion) {
    const chatContainer = $('#chat-container');
    const userMessage = $('<div>').addClass('message shadow-sm');
    const messageText = $('<span>').text(message);

    userMessage.append(messageText);

    if (isEditable) {
        const editIcon = $('<i>').addClass('p-2 bi bi-pencil-fill edit-icon').attr('title', 'Edit query').on('click', function () {
            $('#question').val(originalQuestion).focus();
            autoResizeTextarea($('#question')[0]);

            $('#send-button').removeClass('disabled');
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
    const spinner = $(`
        <div id="spinner" style="display: flex; align-items: center; justify-content: start; margin: 10px 0; padding: 10px;">
            <div class="spinner-border text-primary" role="status" style="width: 1.5rem; height: 1.5rem; margin-right: 15px;">
                <span class="${accessibilityClass}">Loading...</span>
            </div>
            <span style="font-weight: bold; font-size: 15px;">Cargando...</span>
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

/**
 * Displays the document validation results.
 * @param {Array<object>} document_list
 */
function display_document_validation(document_list) {
    const requiredFields = ['document_name', 'document_type', 'causes', 'is_valid'];
    for (const doc of document_list) {
        if (!requiredFields.every(field => field in doc)) {
            console.warn("Document with incorrect structure:", doc);
            continue;
        }
        const docValidationSection = $('<div>').addClass('document-section card mt-2 mb-2');
        const cardBody = $('<div>').addClass('card-body');
        const headerDiv = $('<div>').addClass('d-flex justify-content-between align-items-center mb-2');
        const filenameSpan = $(`
                <div>
                    <span class="text-primary fw-bold">File: </span>
                    <span class="text-secondary">${doc.document_name}</span>
                </div>`);
        const badge_style = doc.is_valid ? 'bg-success' : 'bg-danger';
        const documentBadge = $('<span>')
            .addClass(`badge ${badge_style} p-2`)
            .text(doc.document_type);
        headerDiv.append(filenameSpan).append(documentBadge);
        cardBody.append(headerDiv);

        if (!doc.is_valid && doc.causes && doc.causes.length > 0) {
            const rejectionSection = $('<div>').addClass('rejection-reasons mt-2');
            rejectionSection.append('<h6 class="text-danger">Rejection Causes:</h6>');
            const causesList = doc.causes.map(cause => `<li class="text-secondary">${cause}</li>`).join('');
            rejectionSection.append(`<ul class="list-unstyled">${causesList}</ul>`);
            cardBody.append(rejectionSection);
        } else if (doc.is_valid) {
            const validSection = $('<div>').addClass('mt-2');
            validSection.append('<p class="text-success fw-bold">Valid document.</p>');
            cardBody.append(validSection);
        }
        docValidationSection.append(cardBody);
        displayBotMessage(docValidationSection);
    }
}