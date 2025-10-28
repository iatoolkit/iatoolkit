document.addEventListener('DOMContentLoaded', function() {
    const reloadButton = document.getElementById('force-reload-button');
    if (!reloadButton) return;

    const originalIconClass = 'bi bi-arrow-clockwise';
    const spinnerIconClass = 'spinner-border spinner-border-sm';

    // Configuración de Toastr para que aparezca abajo a la derecha
    toastr.options = { "positionClass": "toast-bottom-right", "preventDuplicates": true };

    reloadButton.addEventListener('click', function(event) {
        event.preventDefault();

        if (reloadButton.disabled) return; // Prevenir doble clic

        // 1. Deshabilitar y mostrar spinner
        reloadButton.disabled = true;
        const icon = reloadButton.querySelector('i');
        icon.className = spinnerIconClass;
        toastr.info('Iniciando recarga de contexto en segundo plano...');

        // 2. Construir la URL dinámicamente
        const company = window.companyShortName;
        const reloadUrl = `/${company}/api/init-context`;

        // 3. Hacer la llamada AJAX con POST
        fetch(reloadUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            // Envía un cuerpo vacío o los datos necesarios
            body: JSON.stringify({})
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error_message || `Error del servidor: ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.status === 'OK') {
                toastr.success(data.message || 'Contexto recargado exitosamente.');
            } else {
                toastr.error(data.error_message || 'Ocurrió un error desconocido.');
            }
        })
        .catch(error => {
            console.error('Error durante la recarga del contexto:', error);
            toastr.error(error.message || 'Error de red al intentar recargar.');
        })
        .finally(() => {
            // 4. Restaurar el botón
            reloadButton.disabled = false;
            icon.className = originalIconClass;
        });
    });
});