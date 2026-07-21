from flask import abort, redirect, url_for
from flask.views import MethodView
from iatoolkit.company_registry import get_company_registry


class RootRedirectView(MethodView):
    """
    Vista que redirige '/home' al home de la primera compañía disponible.
    '/' está reservado para el endpoint de liveness (ver routes.py).
    """

    def get(self):
        registry = get_company_registry()
        companies = registry.get_all_company_instances()

        if companies:
            # Obtener el short_name de la primera compañía registrada.
            # En Python 3.7+, los diccionarios mantienen el orden de inserción.
            first_company_short_name = next(iter(companies))
            return redirect(url_for('home', company_short_name=first_company_short_name))

        # Fallback: no hay compañías registradas, no hay a dónde redirigir.
        abort(404)