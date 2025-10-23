$(document).ready(function () {

    // Evento para enviar el feedback
    $('#submit-feedback').on('click', async function() {
        const feedbackText = $('#feedback-text').val().trim();
        const submitButton = $(this);

        // --- LÓGICA DE COMPATIBILIDAD BS3 / BS5 ---
        // Detecta si Bootstrap 5 está presente.
        const isBootstrap5 = (typeof bootstrap !== 'undefined');

        // Define el HTML del botón de cierre según la versión.
        const closeButtonHtml = isBootstrap5 ?
            '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>' : // Versión BS5
            '<button type="button" class="close" data-dismiss="alert"><span>&times;</span></button>';     // Versión BS3/BS4
        // --- FIN DE LA LÓGICA DE COMPATIBILIDAD ---

        if (!feedbackText) {
            const alertHtml = `
            <div class="alert alert-warning alert-dismissible fade show" role="alert">
                <strong>¡Atención!</strong> Por favor, escribe tu comentario antes de enviar.
                ${closeButtonHtml}
            </div>`;
            $('.modal-body .alert').remove();
            $('.modal-body').prepend(alertHtml);
            return;
        }

        const activeStars = $('.star.active').length;
        if (activeStars === 0) {
            const alertHtml = `
            <div class="alert alert-warning alert-dismissible fade show" role="alert">
                <strong>¡Atención!</strong> Por favor, califica al asistente con las estrellas.
                ${closeButtonHtml}
            </div>`;
            $('.modal-body .alert').remove();
            $('.modal-body').prepend(alertHtml);
            return;
        }

        submitButton.prop('disabled', true);
        submitButton.html('<i class="bi bi-send me-1 icon-spaced"></i>Enviando...');

        const response = await sendFeedback(feedbackText);

        $('#feedbackModal').modal('hide');

        if (response) {
            Swal.fire({ icon: 'success', title: 'Feedback enviado', text: 'Gracias por tu comentario.' });
        } else {
            Swal.fire({ icon: 'error', title: 'Error', text: 'No se pudo enviar el feedback, intente nuevamente.' });
        }
    });

    // Evento para abrir el modal de feedback
    $('#send-feedback-button').on('click', function() {
        $('#submit-feedback').prop('disabled', false);
        $('#submit-feedback').html('<i class="bi bi-send me-1 icon-spaced"></i>Enviar');
        $('.star').removeClass('active hover-active'); // Resetea estrellas
        $('#feedback-text').val(''); // Limpia texto
        $('.modal-body .alert').remove(); // Quita alertas previas
        $('#feedbackModal').modal('show');
    });

    // Evento que se dispara DESPUÉS de que el modal se ha ocultado
    $('#feedbackModal').on('hidden.bs.modal', function () {
        $('#feedback-text').val('');
        $('.modal-body .alert').remove();
        $('.star').removeClass('active');
    });

    // Función para el sistema de estrellas
    window.gfg = function(rating) {
        $('.star').removeClass('active');
        $('.star').each(function(index) {
            if (index < rating) {
                $(this).addClass('active');
            }
        });
    };

    $('.star').hover(
        function() {
            const rating = $(this).data('rating');
            $('.star').removeClass('hover-active');
            $('.star').each(function(index) {
                if ($(this).data('rating') <= rating) {
                    $(this).addClass('hover-active');
                }
            });
        },
        function() {
            $('.star').removeClass('hover-active');
        }
    );
});

const sendFeedback = async function(message) {
    const activeStars = $('.star.active').length;
    const data = {
        "user_identifier": window.user_identifier,
        "message": message,
        "rating": activeStars,
        "space": "spaces/AAQAupQldd4", // Este valor podría necesitar ser dinámico
        "type": "MESSAGE_TRIGGER"
    };
    try {
        // Asumiendo que callLLMAPI está definido globalmente en otro archivo (ej. chat_main.js)
        const responseData = await callLLMAPI('/feedback', data, "POST");
        return responseData;
    } catch (error) {
        console.error("Error al enviar feedback:", error);
        return null;
    }
}