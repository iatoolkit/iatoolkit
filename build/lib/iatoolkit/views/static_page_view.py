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
            'foundation': 'docs/foundation.html',
            'mini_project': 'docs/mini_project.html'
        }

        if page_name not in valid_pages:
            # Si la página no existe, podríamos retornar un 404 o redirigir al index
            return render_template('error.html', message=f"Página no encontrada: {page_name}"), 404

        return render_template(valid_pages[page_name])