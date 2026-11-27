import json
from unittest.mock import MagicMock

import pytest

from iatoolkit.common.interfaces.asset_storage import AssetType
from iatoolkit.infra.redis_session_manager import RedisSessionManager
from iatoolkit.services.chart_service import CHART_RESULT_KEY
from iatoolkit.services.pii_masking_service import PiiMaskingService, normalize_mode

SCHEMA_FILES = {
    "ventas-clientes.yaml": """
clientes:
  description: Clientes
  columns:
    rut: {type: text, pii: true}
    nombre: {type: text, pii: true}
    comuna: {type: text}
""",
    "ventas-creditos.yaml": """
creditos:
  columns:
    - {name: monto, type: numeric}
    - {name: email_contacto, pii: true}
""",
    "otra-clientes.yaml": "clientes:\n  columns:\n    comuna: {pii: true}\n",
}


class FakePipeline:
    def __init__(self, redis):
        self.redis, self.ops = redis, []

    def hset(self, key, field, value):
        self.ops.append(("hset", key, field, value))

    def expire(self, key, seconds):
        self.ops.append(("expire", key, seconds))

    def execute(self):
        for op in self.ops:
            if op[0] == "hset":
                self.redis.hashes.setdefault(op[1], {})[op[2]] = op[3]
            else:
                self.redis.ttls[op[1]] = op[2]


class FakeRedis:
    def __init__(self):
        self.hashes, self.ttls = {}, {}

    def pipeline(self):
        return FakePipeline(self)

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)


@pytest.fixture
def redis_store():
    fake = FakeRedis()
    RedisSessionManager.set_client(fake)
    yield fake
    RedisSessionManager.clear_client()


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("IATOOLKIT_SECRET_KEY", "k" * 64)
    config = MagicMock()
    config.get_configuration.side_effect = lambda company, key: {"pii_masking": "mask"} if key == "privacy" else None
    assets = MagicMock()
    assets.list_files.return_value = list(SCHEMA_FILES)
    assets.read_text.side_effect = lambda company, asset_type, name: SCHEMA_FILES[name]
    sql = MagicMock()
    sql.get_database_dialect.return_value = "postgresql"
    sql.util.serialize = str
    return PiiMaskingService(config, assets, sql)


def test_modes_read_from_company_yaml():
    assert normalize_mode(None) == "off"
    assert normalize_mode(False) == "off"  # YAML reads a bare `off` as false
    assert normalize_mode(True) == "mask"
    assert normalize_mode(" MASK ") == "mask"
    assert normalize_mode("mask_and_restore") == "mask_and_restore"
    assert normalize_mode("restore") is None


def test_off_by_default(service):
    service.configuration_service.get_configuration.side_effect = lambda company, key: None
    rows = [{"rut": "1-9"}]
    assert service.mask_sql_result("acme", "ana", "ventas", "SELECT rut FROM clientes", rows) is rows


def test_pii_columns_are_read_from_the_source_schema_files_only(service):
    assert service.pii_columns("acme", "ventas") == {"rut", "nombre", "email_contacto"}
    service.asset_repo.list_files.assert_called_with("acme", AssetType.SCHEMA)
    service.pii_columns("acme", "ventas")
    assert service.asset_repo.list_files.call_count == 1  # cached


def test_json_result_is_masked_and_tokens_are_kept_for_the_person(service, redis_store):
    result = json.dumps([{"id_cliente": "12.345.678-9", "comuna": "Ñuñoa", "monto": 10},
                         {"id_cliente": None, "comuna": "Maipú", "monto": 5}])

    masked = json.loads(service.mask_sql_result(
        "acme", "ana@acme.cl", "ventas",
        "SELECT rut AS id_cliente, comuna, monto FROM clientes", result))

    token = masked[0]["id_cliente"]
    assert token.startswith("[PII-") and "12.345.678-9" not in json.dumps(masked)
    assert masked[0]["comuna"] == "Ñuñoa" and masked[1]["id_cliente"] is None
    vault = redis_store.hashes["iat:pii:acme:ana@acme.cl"]
    assert json.loads(vault[token]) == "12.345.678-9"
    assert redis_store.ttls["iat:pii:acme:ana@acme.cl"] == 24 * 3600


def test_unparsed_query_naming_a_marked_column_masks_every_column(service, redis_store):
    rows = [{"a": "x", "b": 1}]
    masked = service.mask_sql_result("acme", "ana", "ventas", "SELEC rut ((( FROM", rows)
    assert masked[0]["a"].startswith("[PII-") and masked[0]["b"].startswith("[PII-")


def test_the_model_can_filter_by_a_token_and_another_person_cannot(service, redis_store):
    masked = service.mask_sql_result("acme", "ana", "ventas", "SELECT rut FROM clientes", [{"rut": "1-9"}])
    token = masked[0]["rut"]

    query = f"SELECT * FROM creditos WHERE rut = '{token}'"
    assert service.restore_sql("acme", "ana", query) == "SELECT * FROM creditos WHERE rut = '1-9'"
    assert service.restore_sql("acme", "pedro", query) == query


def test_files_built_for_the_person_carry_the_values(service, redis_store):
    masked = service.mask_sql_result("acme", "ana", "ventas", "SELECT nombre FROM clientes",
                                     [{"nombre": "Ana Pérez"}])
    token = masked[0]["nombre"]
    restored = service.restore_arguments("acme", "ana", {"rows": [[token, 3]], "title": "x"})
    assert restored == {"rows": [["Ana Pérez", 3]], "title": "x"}


def test_chart_summary_for_the_model_hides_marked_x_values(service, redis_store):
    result = {
        "status": "ok",
        "data": {"columns": ["cliente", "monto"], "rows": [["Ana Pérez", 10], ["Luis Soto", 5]],
                 "summary_by_series": {"Monto": {"max": {"x": "Ana Pérez", "value": 10}}}},
        CHART_RESULT_KEY: {"columns": ["cliente", "monto"], "rows": [["Ana Pérez", 10], ["Luis Soto", 5]]},
    }
    masked = service.mask_chart_result(
        "acme", "ana", {"database_key": "ventas", "query": "SELECT nombre AS cliente, monto FROM clientes"},
        result)

    model_view = json.dumps(masked["data"], ensure_ascii=False)
    assert "Ana Pérez" not in model_view and "Luis Soto" not in model_view
    assert masked["data"]["rows"][0][1] == 10
    # The chart the person sees keeps the names.
    assert masked[CHART_RESULT_KEY]["rows"][0][0] == "Ana Pérez"


def test_chart_with_inline_data_hides_values_the_model_wrote_as_tokens(service, redis_store):
    token = service.mask_sql_result("acme", "ana", "ventas", "SELECT nombre FROM clientes",
                                    [{"nombre": "Ana Pérez"}])[0]["nombre"]
    result = {"data": {"rows": [["Ana Pérez", 10]]}, CHART_RESULT_KEY: {"rows": [["Ana Pérez", 10]]}}

    masked = service.mask_chart_result("acme", "ana", {"data": [{"cliente": token, "monto": 10}]}, result)

    assert masked["data"]["rows"][0][0] == token


def test_person_view_only_when_the_company_restores(service, redis_store):
    assert service.person_view("acme", "ana") is None  # mode is `mask`
    service.configuration_service.get_configuration.side_effect = \
        lambda company, key: {"pii_masking": "mask_and_restore"} if key == "privacy" else None
    assert service.person_view("acme", None) is None
    assert service.person_view("acme", "ana") is not None


def test_a_turn_result_is_restored_for_its_person_only(service, redis_store):
    service.configuration_service.get_configuration.side_effect = \
        lambda company, key: {"pii_masking": "mask_and_restore"} if key == "privacy" else None
    token = service.mask_sql_result("acme", "ana", "ventas", "SELECT nombre FROM clientes",
                                    [{"nombre": "Ana <Pérez>"}])[0]["nombre"]
    result = {"answer": f"<p>Cliente {token}</p>", "answer_text": f"Cliente {token}",
              "structured_output": {"cliente": token}, "query_id": 7}

    restored = service.person_view("acme", "ana").restore_result(result)

    assert restored["answer"] == "<p>Cliente Ana &lt;Pérez&gt;</p>"
    assert restored["answer_text"] == "Cliente Ana <Pérez>"
    assert restored["structured_output"] == {"cliente": "Ana <Pérez>"}
    assert result["answer_text"] == f"Cliente {token}"  # the original is not touched
    assert service.person_view("acme", "pedro").restore_result(result)["answer_text"] == f"Cliente {token}"
