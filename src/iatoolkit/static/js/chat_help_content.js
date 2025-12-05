$(document).ready(function () {

    let helpContent = null; // Variable para cachear el contenido de ayuda

    // Evento de clic en el botón de ayuda
    $('#open-help-button').on('click', async function () {
        const helpModal = new bootstrap.Modal(document.getElementById('helpModal'));
        const accordionContainer = $('#help-accordion-container');
        const spinner = $('#help-spinner');

        // Si el contenido no se ha cargado, hacer la llamada a la API
        if (helpContent) {
            // Si el contenido ya está cacheado, solo muestra el modal
            helpModal.show();
            return;
        }

        spinner.show();
        accordionContainer.hide();
        helpModal.show();

        try {
            const helpContent = await callToolkit('/api/help-content', {}, "POST");

            if (!helpContent) {
                toastr.error('No se pudo cargar la guía de uso. Por favor, intente más tarde.');
                spinner.hide();
                helpModal.hide();
                return;
            }

            // Construir el HTML del acordeón y mostrarlo
            buildHelpAccordion(helpContent);
            spinner.hide();
            accordionContainer.show();

        } catch (error) {
            console.error("Error al cargar el contenido de ayuda:", error);
            toastr.error('Ocurrió un error de red al cargar la guía.');
            spinner.hide();
            helpModal.hide();
        }
    });

    /**
     * Construye dinámicamente el HTML para el acordeón de ayuda a partir de los datos.
     * @param {object} data El objeto JSON con el contenido de ayuda.
     */
    function buildHelpAccordion(data) {
        const container = $('#help-accordion-container');
        container.empty(); // Limpiar cualquier contenido previo

        let accordionHtml = '';

        if (data.example_questions) {
            let contentHtml = '';
            data.example_questions.forEach(cat => {
                contentHtml += `<h6 class="fw-bold">${cat.category}</h6><ul>`;
                cat.questions.forEach(q => contentHtml += `<li>${q}</li>`);
                contentHtml += `</ul>`;
            });
            accordionHtml += createAccordionItem('examples', 'Sample questions', contentHtml, true);
        }

        if (data.data_sources) {
            let contentHtml = '<dl>';
            data.data_sources.forEach(p => {
                contentHtml += `<dt>${p.source}</dt><dd>${p.description}</dd>`;
            });
            contentHtml += `</dl>`;
            accordionHtml += createAccordionItem('sources', 'Data available', contentHtml );
        }

        if (data.best_practices) {
            let contentHtml = '<dl>';
            data.best_practices.forEach(p => {
                contentHtml += `<dt>${p.title}</dt><dd>${p.description}`;
                if (p.example) {
                    contentHtml += `<br><small class="text-muted"><em>Ej: "${p.example}"</em></small>`;
                }
                contentHtml += `</dd>`;
            });
            contentHtml += `</dl>`;
            accordionHtml += createAccordionItem('practices', 'Best practices', contentHtml);
        }

        if (data.capabilities) {
            let contentHtml = `<div class="row">`;
            contentHtml += `<div class="col-md-6"><h6 class="fw-bold">Puede hacer:</h6><ul>${data.capabilities.can_do.map(item => `<li>${item}</li>`).join('')}</ul></div>`;
            contentHtml += `<div class="col-md-6"><h6 class="fw-bold">No puede hacer:</h6><ul>${data.capabilities.cannot_do.map(item => `<li>${item}</li>`).join('')}</ul></div>`;
            contentHtml += `</div>`;
            accordionHtml += createAccordionItem('capabilities', 'Capabilities and limits', contentHtml);
        }

        container.html(accordionHtml);
    }

    /**
     * Helper para crear un item del acordeón de Bootstrap.
     * @param {string} id El ID base para los elementos.
     * @param {string} title El título que se muestra en el botón del acordeón.
     * @param {string} contentHtml El HTML que va dentro del cuerpo colapsable.
     * @param {boolean} isOpen Si el item debe estar abierto por defecto.
     * @returns {string} El string HTML del item del acordeón.
     */
    function createAccordionItem(id, title, contentHtml, isOpen = false) {
        const showClass = isOpen ? 'show' : '';
        const collapsedClass = isOpen ? '' : 'collapsed';

        return `
            <div class="accordion-item">
                <h2 class="accordion-header" id="heading-${id}">
                    <button class="accordion-button ${collapsedClass}" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-${id}" aria-expanded="${isOpen}" aria-controls="collapse-${id}">
                        ${title}
                    </button>
                </h2>
                <div id="collapse-${id}" class="accordion-collapse collapse ${showClass}" aria-labelledby="heading-${id}" data-bs-parent="#help-accordion-container">
                    <div class="accordion-body">
                        ${contentHtml}
                    </div>
                </div>
            </div>`;
    }
});