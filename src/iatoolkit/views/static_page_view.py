from flask import render_template
from flask.views import MethodView
from injector import inject


class StaticPageView(MethodView):
    """
    View genérica para servir páginas estáticas simples (sin lógica de negocio compleja).
    """

    @inject
    def __init__(self):
        pass

    def get(self, page_name: str):
        # Mapeo seguro de nombres de página a plantillas
        # Esto evita que se intente cargar cualquier archivo arbitrario
        valid_pages = {
            'foundation': 'foundation.html',
            'implementation_plan': 'implementation_plan.html'
        }

        if page_name not in valid_pages:
            # Si la página no existe, podríamos retornar un 404 o redirigir al index
            return render_template('error.html', error_message="Página no encontrada"), 404

        return render_template(valid_pages[page_name])