from flask import Flask

from iatoolkit.common.routes import register_views


def test_register_views_does_not_publish_invocations_route():
    app = Flask(__name__)
    app.config["VERSION"] = "test"

    register_views(app)

    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/<company_short_name>/api/invocations" not in rules
