$(document).ready(function () {
    // Evento para abrir el modal de historial
    const historyModal = $('#historyModal');

    $('#history-button').on('click', function() {
        historyModal.modal('show');
        loadHistory();
    });


    // Función para cargar el historial
    async function loadHistory() {
        const historyLoading = $('#history-loading');
        const historyContent = $('#history-content');
        const historyTable = historyContent.find('table');
        const noHistoryMessage = $('#no-history-message');

        // prepare UI for loading
        historyLoading.show();
        historyContent.hide();
        historyTable.show();
        noHistoryMessage.hide();

        // cal the toolkit, handle the response and errors
        const data = await callToolkit("/api/history", {}, "POST");

        if (!data || !data.history) {
            historyLoading.hide();
            toastr.error(t_js('error_loading_history'));
            return;
        }

        if (data.history.length === 0) {
            historyTable.hide();
            noHistoryMessage.show();
        } else
            displayAllHistory(data.history);

        historyLoading.hide();
        historyContent.show();
    }

    // Función para mostrar todo el historial
    function displayAllHistory(historyData) {
        const historyTableBody = $('#history-table-body');

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

            const edit_link = $('<a>')
                .attr('href', 'javascript:void(0);')
                .addClass('edit-pencil')
                .attr('title', t_js('edit_query'))
                .data('query', item.query)
                .append(icon);

            const row = $('<tr>').append(
                $('<td>').addClass('text-nowrap').text(formatDate(item.created_at)),
                $('<td>').text(item.query),
                $('<td>').append(edit_link),
            );
            historyTableBody.append(row);
        });
    }

    function formatDate(dateString) {
        const date = new Date(dateString);
        const padTo2Digits = (num) => num.toString().padStart(2, '0');

        const day = padTo2Digits(date.getDate());
        const month = padTo2Digits(date.getMonth() + 1);
        const year = date.getFullYear();
        const hours = padTo2Digits(date.getHours());
        const minutes = padTo2Digits(date.getMinutes());

        return `${day}-${month} ${hours}:${minutes}`;
    }

    // event handler for the edit pencil icon
    $('#history-table-body').on('click', '.edit-pencil', function() {
        const queryText = $(this).data('query');

        // copy the text to the chat input box
        if (queryText) {
            $('#question').val(queryText);
            autoResizeTextarea($('#question')[0]);
            $('#send-button').removeClass('disabled');

            // Cerrar el modal
            $('#historyModal').modal('hide');

            // Hacer focus en el textarea
            if (window.innerWidth > 768)
                $('#question').focus();
        }
    });
});