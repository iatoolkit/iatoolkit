from flask import redirect, url_for
from flask.views import MethodView
from iatoolkit.company_registry import get_company_registry


class RootRedirectView(MethodView):
    """
    Vista que redirige la raíz '/' al home de la primera compañía disponible.
    """

    def get(self):
        registry = get_company_registry()
        companies = registry.get_all_company_instances()

        if companies:
            # Obtener el short_name de la primera compañía registrada.
            # En Python 3.7+, los diccionarios mantienen el orden de inserción.
            first_company_short_name = next(iter(companies))
            return redirect(url_for('home', company_short_name=first_company_short_name))

        # Fallback: Si no hay compañías, ir al index genérico (o a un 404)
        return redirect(url_for('index'))