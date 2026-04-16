$(document).ready(function () {
    const feedbackModal = $('#feedbackModal');
    $('#submit-feedback').on('click', function () {
        sendFeedback(this);
    });

    // Evento para enviar el feedback
    async function sendFeedback(submitButton) {
        toastr.options = {"positionClass": "toast-bottom-right", "preventDuplicates": true};
        const feedbackText = $('#feedback-text').val().trim();
        const activeStars = $('.star.active').length;

        if (!feedbackText) {
            toastr.error(t_js('feedback_comment_error'));
            return;
        }

        if (activeStars === 0) {
            toastr.error(t_js('feedback_rating_error'));
            return;
        }

        submitButton.disabled = true;

        // call the IAToolkit API to send feedback
        const data = {
            "user_identifier": window.user_identifier,
            "message": feedbackText,
            "rating": activeStars,
        };

        const responseData = await callToolkit('/api/feedback', data, "POST");
        if (responseData)
            toastr.success(t_js('feedback_sent_success_body'), t_js('feedback_sent_success_title'));
        else
            toastr.error(t_js('feedback_sent_error'));

        submitButton.disabled = false;
        feedbackModal.modal('hide');
    }

// Evento para abrir el modal de feedback
$('#send-feedback-button').on('click', function () {
    $('#submit-feedback').prop('disabled', false);
    $('.star').removeClass('active hover-active'); // Resetea estrellas
    $('#feedback-text').val('');
    feedbackModal.modal('show');
});

// Evento que se dispara DESPUÉS de que el modal se ha ocultado
$('#feedbackModal').on('hidden.bs.modal', function () {
    $('#feedback-text').val('');
    $('.star').removeClass('active');
});

// Tool for the star rating system
window.gfg = function (rating) {
    $('.star').removeClass('active');
    $('.star').each(function (index) {
        if (index < rating) {
            $(this).addClass('active');
        }
    });
};

$('.star').hover(
    function () {
        const rating = $(this).data('rating');
        $('.star').removeClass('hover-active');
        $('.star').each(function (index) {
            if ($(this).data('rating') <= rating) {
                $(this).addClass('hover-active');
            }
        });
    },
    function () {
        $('.star').removeClass('hover-active');
    });

});
