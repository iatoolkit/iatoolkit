# iatoolkit/views/index_view.py

from flask import render_template, request
from flask.views import MethodView


class IndexView(MethodView):
    """
    Handles the rendering of the generic landing page, which no longer depends
    on a specific company.
    """

    def get(self):
        lang = request.args.get("lang", "en")  # default en inglés

        if lang == "es":
            return render_template("index_es.html")

        return render_template("index.html")
