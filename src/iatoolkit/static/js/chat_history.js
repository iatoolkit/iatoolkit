$(document).ready(function () {
    // Evento para abrir el modal de historial
    $('#history-button').on('click', function() {
        loadHistory();
        $('#historyModal').modal('show');
    });

    // Evento delegado para el icono de copiar.
    // Se adjunta UNA SOLA VEZ al cuerpo de la tabla y funciona para todas las filas
    // que se añadan dinámicamente.
    $('#history-table-body').on('click', '.copy-query-icon', function() {
        const queryText = $(this).data('query');

        // Copiar el texto al textarea del chat
        if (queryText) {
            $('#question').val(queryText);
            autoResizeTextarea($('#question')[0]);
            $('#send-button').removeClass('disabled');

            // Cerrar el modal
            $('#historyModal').modal('hide');

            // Hacer focus en el textarea
            $('#question').focus();
        }
    });

    // Variables globales para el historial
    let historyData = [];

    // Función para cargar el historial
    async function loadHistory() {
        const historyLoading = $('#history-loading');
        const historyError = $('#history-error');
        const historyContent = $('#history-content');

        // Mostrar loading
        historyLoading.show();
        historyError.hide();
        historyContent.hide();

        try {
            const data = {
                external_user_id: window.externalUserId
            };

            const responseData = await callLLMAPI("/history", data, "POST");

            if (responseData && responseData.history) {
                // Guardar datos globalmente
                historyData = responseData.history;

                // Mostrar todos los datos
                displayAllHistory();

                // Mostrar contenido
                historyContent.show();
            } else {
                throw new Error('La respuesta del servidor no contenía el formato esperado.');
            }
        } catch (error) {
            console.error("Error al cargar historial:", error);

            const friendlyErrorMessage = "No hemos podido cargar tu historial en este momento. Por favor, cierra esta ventana y vuelve a intentarlo en unos instantes.";
            const errorHtml = `
                <div class="text-center p-4">
                    <i class="bi bi-exclamation-triangle text-danger" style="font-size: 2.5rem; opacity: 0.8;"></i>
                    <h5 class="mt-3 mb-2">Ocurrió un Problema</h5>
                    <p class="text-muted">${friendlyErrorMessage}</p>
                </div>
            `;
            historyError.html(errorHtml).show();
        } finally {
            historyLoading.hide();
        }
    }

    // Función para mostrar todo el historial
    function displayAllHistory() {
        const historyTableBody = $('#history-table-body');

        // Limpiar tabla
        historyTableBody.empty();

        // Filtrar solo consultas que son strings simples
        const filteredHistory = historyData.filter(item => {
            try {
                JSON.parse(item.query);
                return false;
            } catch (e) {
                return true;
            }
        });

        // Poblar la tabla
        filteredHistory.forEach((item, index) => {
            const icon = $('<i>').addClass('bi bi-pencil-fill');

            const link = $('<a>')
                .attr('href', 'javascript:void(0);')
                .addClass('copy-query-icon')
                .attr('title', 'Copiar consulta al chat')
                .data('query', item.query)
                .append(icon);

            const row = $('<tr>').append(
                $('<td>').text(index + 1),
                $('<td>').addClass('date-cell').text(formatDate(item.created_at)),
                $('<td>').text(item.query),
                $('<td>').addClass('text-center').append(link)
            );

            historyTableBody.append(row);
        });
    }

    // Función para formatear fecha
    function formatDate(dateString) {
        const date = new Date(dateString);

        const padTo2Digits = (num) => num.toString().padStart(2, '0');

        const day = padTo2Digits(date.getDate());
        const month = padTo2Digits(date.getMonth() + 1);
        const year = date.getFullYear();
        const hours = padTo2Digits(date.getHours());
        const minutes = padTo2Digits(date.getMinutes());

        return `${day}-${month}-${year} ${hours}:${minutes}`;
    }
});