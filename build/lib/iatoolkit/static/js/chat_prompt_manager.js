$(document).ready(function () {
// --- PROMPT ASSISTANT FUNCTIONALITY ---
    const $promptCollapse = $('#prompt-assistant-collapse');

    if ($promptCollapse.length) {
        $promptCollapse.on('shown.bs.collapse', function () {
            // Scroll to bottom smoothly when the collapse is shown
            $('html, body').animate(
                { scrollTop: $(document).height() },
                'slow'
            );
        });
    }

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
