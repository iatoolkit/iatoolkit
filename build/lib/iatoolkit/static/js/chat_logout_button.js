document.addEventListener('DOMContentLoaded', function() {
    const logoutButton = document.getElementById('logout-button');
    if (!logoutButton) {
        console.warn('El botón de logout con id "logout-button" no fue encontrado.');
        return;
    }

    if (window.toastr) {
        toastr.options = { "positionClass": "toast-bottom-right", "preventDuplicates": true };
    }

    logoutButton.addEventListener('click', async function(event) {
        event.preventDefault();

        try {
            const apiPath = '/api/logout';
            const data = await callToolkit(apiPath, null, 'GET');

            // Procesar la respuesta
            if (data && data.status === 'success' && data.url) {
                window.top.location.href = data.url;
            } else {
                // Si algo falla, callToolkit usualmente muestra un error.
                // Mostramos un toast como fallback.
                if (window.toastr) {
                    toastr.error('No se pudo procesar el cierre de sesión. Por favor, intente de nuevo.');
                }
            }
        } catch (error) {
            console.error('Error durante el logout:', error);
            if (window.toastr) {
                toastr.error('Ocurrió un error de red al intentar cerrar sesión.');
            }
        }
    });
});