from iatoolkit.common import pii_masking

KEY = b"test-key"
PII = {"rut", "email", "nombre"}


def sensitive(query, dialect="postgres"):
    return pii_masking.sensitive_output_columns(query, PII, dialect)


class TestSensitiveOutputColumns:
    def test_marked_column_selected_by_name(self):
        assert {"rut", "email"} <= sensitive("SELECT rut, email, monto FROM clientes")
        assert "monto" not in sensitive("SELECT rut, email, monto FROM clientes")

    def test_alias_of_marked_column_is_sensitive(self):
        result = sensitive("SELECT c.rut AS id_cliente, monto AS total FROM clientes c")
        assert "id_cliente" in result
        assert "total" not in result

    def test_expressions_over_marked_columns_are_sensitive(self):
        result = sensitive(
            "SELECT UPPER(email) AS correo, nombre || ' (' || rut || ')' AS cliente, "
            "MAX(rut) AS ultimo, string_agg(email, ',') AS correos FROM clientes GROUP BY 1, 2")
        assert {"correo", "cliente", "ultimo", "correos"} <= result

    def test_counts_reveal_no_value(self):
        result = sensitive("SELECT COUNT(DISTINCT rut) AS clientes, COUNT(email) AS con_correo FROM clientes")
        assert "clientes" not in result
        assert "con_correo" not in result

    def test_aliases_through_subqueries_and_ctes(self):
        result = sensitive(
            "WITH base AS (SELECT rut AS id, monto FROM creditos) "
            "SELECT x.id AS cliente, x.monto FROM (SELECT id, monto FROM base) x")
        assert {"id", "cliente"} <= result
        assert "monto" not in result

    def test_unparseable_query_returns_none(self):
        assert pii_masking.sensitive_output_columns("SELEC FROM (((", PII) is None

    def test_no_marked_columns_means_nothing_sensitive(self):
        assert pii_masking.sensitive_output_columns("SELECT rut FROM t", set()) == set()

    def test_unknown_dialect_still_parses(self):
        assert "id" in pii_masking.sensitive_output_columns("SELECT rut AS id FROM t", PII, "nonexistent")


class TestTokens:
    def test_token_is_stable_and_keyed(self):
        token = pii_masking.make_token("12.345.678-9", KEY)
        assert token == pii_masking.make_token("12.345.678-9", KEY)
        assert token != pii_masking.make_token("12.345.678-9", b"other-key")
        assert pii_masking.TOKEN_RE.fullmatch(token)

    def test_types_do_not_collide(self):
        assert pii_masking.make_token(12345678, KEY) != pii_masking.make_token("12345678", KEY)

    def test_mask_rows_keeps_nulls_and_other_columns(self):
        rows = [{"rut": "1-9", "monto": 10}, {"rut": None, "monto": 5}]
        masked, columns, count = pii_masking.mask_rows(
            rows, lambda name: name == "rut", lambda value: pii_masking.make_token(value, KEY))
        assert masked[0]["rut"].startswith("[PII-") and masked[0]["monto"] == 10
        assert masked[1]["rut"] is None
        assert columns == {"rut"} and count == 1

    def test_replace_tokens_in_sql_escapes_quotes(self):
        token = pii_masking.make_token("O'Higgins", KEY)
        values = {token: "O'Higgins"}
        query = f"SELECT * FROM t WHERE nombre = '{token}' AND x = '[PII-000000000000]'"
        restored = pii_masking.replace_tokens(
            query, lambda t: values.get(t, pii_masking.MISSING), sql=True)
        assert "nombre = 'O''Higgins'" in restored
        assert "[PII-000000000000]" in restored  # unknown tokens stay

    def test_replace_tokens_in_payload(self):
        token = pii_masking.make_token("ana@acme.cl", KEY)
        payload = {"rows": [[token, 3]], "title": f"Cliente {token}", "n": 1}
        restored = pii_masking.replace_tokens_in(
            payload, lambda t: "ana@acme.cl" if t == token else pii_masking.MISSING)
        assert restored == {"rows": [["ana@acme.cl", 3]], "title": "Cliente ana@acme.cl", "n": 1}
