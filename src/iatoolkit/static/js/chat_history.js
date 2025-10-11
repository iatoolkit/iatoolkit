$(document).ready(function () {
    // Evento para abrir el modal de historial
    $('#history-button').on('click', function() {
        loadHistory();
        $('#historyModal').modal('show');
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
                throw new Error('No se recibieron datos del historial');
            }
        } catch (error) {
            console.error("Error al cargar historial:", error);
            const errorHtml = `
                <div class="alert alert-branded-danger alert-dismissible show" role="alert">
                    <strong>Error al cargar el historial:</strong> ${error.message}
                    <button type="button" class="close" data-dismiss="alert">
                        <span>&times;</span>
                    </button>
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

        // Filtrar solo consultas que son strings simples (no objetos JSON)
        const filteredHistory = historyData.filter(item => {
            try {
                // Intentar parsear como JSON
                const parsed = JSON.parse(item.query);
                // Si se puede parsear y es un objeto, filtrarlo
                return false;
            } catch (e) {
                // Si no se puede parsear, es un string simple, incluirlo
                return true;
            }
        });

        // Poblar tabla solo con las consultas filtradas
        filteredHistory.forEach((item, index) => {
            const row = $(`
                <tr>
                    <td>${index + 1}</td>
                    <td>${formatDate(item.created_at)}</td>
                    <td class="query-cell" style="cursor: pointer;" title="Haz clic para copiar esta consulta al chat">${item.query}</td>
                </tr>
            `);
            historyTableBody.append(row);
        });

        // Agregar evento de clic a las celdas de consulta
        historyTableBody.on('click', '.query-cell', function() {
            const queryText = $(this).text();
            
            // Copiar el texto al textarea del chat
            $('#question').val(queryText);
            
            // Cerrar el modal
            $('#historyModal').modal('hide');
            
            // Hacer focus en el textarea para que el usuario pueda editar si lo desea
            $('#question').focus();
        });
    }

    // Función para formatear fecha
    function formatDate(dateString) {
        const date = new Date(dateString);
        return date.toLocaleDateString('es-CL', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

});

