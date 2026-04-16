$(document).ready(function () {
    $('#force-reload-button').on('click', function() {
        reloadButton(this);
     });

    async function reloadButton(button) {
        const originalIconClass = 'bi bi-arrow-clockwise';
        const spinnerIconClass = 'spinner-border spinner-border-sm';

        // Configuración de Toastr para que aparezca abajo a la derecha
        toastr.options = {"positionClass": "toast-bottom-right", "preventDuplicates": true};

        // 1. Deshabilitar y mostrar spinner
        button.disabled = true;
        const icon = button.querySelector('i');
        icon.className = spinnerIconClass;
        toastr.info(t_js('reload_init'));

        // 2. prepare the api parameters
        const apiPath = '/api/init-context';
        const payload = {
            'user_identifier': window.user_identifier,
            'model': (window.currentLlmModel || window.defaultLlmModel || '')
            };

        // 3. make the call to callToolkit
        const data = await callToolkit(apiPath, payload, 'POST');
        if (data) {
            if (data.status === 'OK')
                toastr.success(data.message || 'Contexto reloaded.');
            else
                toastr.error(data.error_message || 'error during reload');
        }

        button.disabled = false;
        icon.className = originalIconClass;
    }
});