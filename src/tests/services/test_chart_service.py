import datetime
import decimal
from unittest.mock import MagicMock

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.chart_service import (
    CHART_MARKER_RE,
    CHART_RESULT_KEY,
    ChartService,
    chart_marker,
)
from iatoolkit.services.sql_service import SqlService

COMPANY = "acme"

MONTHS = [
    {"mes": "2026-01", "garantias": 4398},
    {"mes": "2026-02", "garantias": 3829},
    {"mes": "2026-03", "garantias": 4351},
    {"mes": "2026-04", "garantias": 3955},
]


@pytest.fixture
def sql():
    return MagicMock(spec=SqlService)


@pytest.fixture
def service(sql):
    return ChartService(sql_service=sql)


class TestFromSql:
    def test_runs_the_query_like_iat_sql_query_and_returns_a_chart(self, service, sql):
        sql.exec_sql.return_value = MONTHS

        result = service.create_chart(
            COMPANY, type="bar", title="Garantías 2026", x="mes",
            series=[{"field": "garantias", "label": "Garantías"}],
            database_key="erp", query="SELECT mes, garantias FROM t",
        )

        sql.exec_sql.assert_called_once_with(
            COMPANY, database_key="erp", query="SELECT mes, garantias FROM t", format="dict"
        )
        chart = result[CHART_RESULT_KEY]
        assert chart["type"] == "bar"
        assert chart["columns"] == ["mes", "garantias"]
        assert chart["rows"][0] == ["2026-01", 4398]
        assert chart["source"] == {"kind": "sql", "database_key": "erp", "query": "SELECT mes, garantias FROM t"}
        assert result["marker"] == chart_marker(chart["id"])
        assert CHART_MARKER_RE.fullmatch(result["marker"])

    def test_the_model_reads_the_rows_when_few(self, service, sql):
        sql.exec_sql.return_value = MONTHS

        result = service.create_chart(COMPANY, x="mes", series=["garantias"],
                                      database_key="erp", query="SELECT 1")

        assert result["data"]["rows"] == [[r["mes"], r["garantias"]] for r in MONTHS]
        # The extremes are computed, not left for the model to read off the rows.
        assert result["data"]["summary_by_series"]["garantias"]["max"] == {"x": "2026-01", "value": 4398}
        assert result["data"]["summary_by_series"]["garantias"]["min"] == {"x": "2026-02", "value": 3829}
        assert result["series"] == ["garantias"]

    def test_the_model_reads_a_summary_when_many(self, service, sql):
        sql.exec_sql.return_value = [{"d": f"2026-01-{i:02d}", "v": i} for i in range(1, 32)] * 2

        result = service.create_chart(COMPANY, x="d", series=["v"], database_key="erp", query="q")

        summary = result["data"]["summary_by_series"]["v"]
        assert result["data"]["row_count"] == 62
        assert summary["max"]["value"] == 31
        assert summary["min"]["value"] == 1
        assert "rows" not in result["data"]

    def test_sql_errors_reach_the_model_unchanged(self, service, sql):
        sql.exec_sql.side_effect = IAToolkitException(IAToolkitException.ErrorType.INVALID_SQL, "no such column")

        with pytest.raises(IAToolkitException) as error:
            service.create_chart(COMPANY, x="mes", series=["n"], database_key="erp", query="SELECT n")

        assert error.value.error_type == IAToolkitException.ErrorType.INVALID_SQL

    def test_database_values_become_plain_json(self, service, sql):
        sql.exec_sql.return_value = [
            {"dia": datetime.date(2026, 1, 5), "monto": decimal.Decimal("10.50")},
            {"dia": datetime.datetime(2026, 1, 6), "monto": decimal.Decimal("3")},
        ]

        chart = service.create_chart(COMPANY, type="line", x="dia", series=["monto"],
                                     database_key="erp", query="q")[CHART_RESULT_KEY]

        assert chart["rows"] == [["2026-01-05", 10.5], ["2026-01-06", 3]]


class TestInline:
    def test_a_few_rows_written_by_the_model(self, service, sql):
        chart = service.create_chart(
            COMPANY, type="pie", x="segmento", series=[{"field": "clientes"}],
            data=[{"segmento": "Pyme", "clientes": 120}, {"segmento": "Corp", "clientes": "30"}],
        )[CHART_RESULT_KEY]

        sql.exec_sql.assert_not_called()
        assert chart["rows"] == [["Pyme", 120], ["Corp", 30]]
        assert chart["source"] == {"kind": "inline"}

    def test_data_may_arrive_as_a_json_string(self, service):
        chart = service.create_chart(COMPANY, type="bar", x="a", series=["b"],
                                     data='[{"a": "x", "b": 1}]')[CHART_RESULT_KEY]

        assert chart["rows"] == [["x", 1]]


class TestValidation:
    @pytest.mark.parametrize("kwargs, message", [
        ({"series": ["v"], "data": [{"v": 1}]}, "Falta x"),
        ({"x": "a", "data": [{"a": 1}]}, "Falta series"),
        ({"x": "a", "series": ["b"]}, "Faltan los datos"),
        ({"x": "a", "series": ["b"], "database_key": "erp"}, "juntos"),
        ({"x": "a", "series": ["b"], "type": "radar", "data": [{"a": 1, "b": 2}]}, "type debe ser"),
        ({"x": "a", "series": ["b", "c"], "type": "pie", "data": [{"a": 1, "b": 2, "c": 3}]}, "exactamente una serie"),
        ({"x": "a", "series": ["b"], "format": "euros", "data": [{"a": 1, "b": 2}]}, "format debe ser"),
        ({"x": "zz", "series": ["b"], "data": [{"a": 1, "b": 2}]}, "'zz' (x) no está"),
        ({"x": "a", "series": ["zz"], "data": [{"a": 1, "b": 2}]}, "'zz' (series) no está"),
        ({"x": "a", "series": ["b"], "data": [{"a": 1, "b": "mucho"}]}, "no numérico"),
    ])
    def test_errors_tell_the_model_what_to_fix(self, service, kwargs, message):
        with pytest.raises(IAToolkitException) as error:
            service.create_chart(COMPANY, **kwargs)

        assert error.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER
        assert message in error.value.message

    def test_an_empty_result_is_not_a_chart(self, service, sql):
        sql.exec_sql.return_value = []

        with pytest.raises(IAToolkitException) as error:
            service.create_chart(COMPANY, x="a", series=["b"], database_key="erp", query="q")

        assert "no devolvió filas" in error.value.message


class TestCaps:
    def test_too_many_rows_are_cut_with_a_note(self, service, sql):
        sql.exec_sql.return_value = [{"i": i, "v": i} for i in range(ChartService.MAX_ROWS + 20)]

        result = service.create_chart(COMPANY, type="bar", x="i", series=["v"], database_key="erp", query="q")

        assert len(result[CHART_RESULT_KEY]["rows"]) == ChartService.MAX_ROWS
        assert result["notes"] and str(ChartService.MAX_ROWS + 20) in result["notes"][0]

    def test_a_pie_keeps_the_largest_slices_and_sums_the_rest(self, service):
        data = [{"k": f"c{i}", "v": i} for i in range(1, 21)]

        chart = service.create_chart(COMPANY, type="pie", x="k", series=["v"], data=data)[CHART_RESULT_KEY]

        assert len(chart["rows"]) == ChartService.MAX_PIE_SLICES
        assert chart["rows"][0] == ["c20", 20]
        assert chart["rows"][-1][0] == ChartService.OTHERS_LABEL
        assert sum(row[1] for row in chart["rows"]) == sum(range(1, 21))


class TestSuggestedType:
    def test_time_on_x_is_a_line(self, service, sql):
        sql.exec_sql.return_value = MONTHS

        result = service.create_chart(COMPANY, x="mes", series=["garantias"], database_key="erp", query="q")

        assert result["type"] == "line"
        assert result["type_suggested"] is True

    def test_month_names_are_time(self, service):
        data = [{"m": m, "v": 1} for m in ["Ene", "Feb", "Mar", "Abr", "May"]]

        assert service.create_chart(COMPANY, x="m", series=["v"], data=data)["type"] == "line"

    def test_categories_are_bars(self, service):
        data = [{"c": c, "v": 1} for c in ["Norte", "Sur", "Centro", "Este", "Oeste"]]

        assert service.create_chart(COMPANY, x="c", series=["v"], data=data)["type"] == "bar"

    def test_a_type_the_model_chose_is_kept(self, service, sql):
        sql.exec_sql.return_value = MONTHS

        result = service.create_chart(COMPANY, type="bar", x="mes", series=["garantias"],
                                      database_key="erp", query="q")

        assert result["type"] == "bar"
        assert result["type_suggested"] is False


class TestEchartsOption:
    def _option(self, service, **kwargs):
        return service.create_chart(COMPANY, **kwargs)[CHART_RESULT_KEY]["echarts"]

    def test_bars_by_category_from_a_dataset(self, service):
        option = self._option(service, type="bar", title="T", x="c", series=["v"],
                              data=[{"c": "a", "v": 1}, {"c": "b", "v": 2}])

        assert option["dataset"]["source"] == [["c", "v"], ["a", 1], ["b", 2]]
        assert option["xAxis"]["type"] == "category"
        assert option["series"] == [{"type": "bar", "name": "v", "encode": {"x": "c", "y": "v"}}]
        assert option["title"]["text"] == "T"
        assert option["tooltip"]["trigger"] == "axis"

    def test_two_periods_are_two_series_with_a_legend(self, service):
        option = self._option(service, type="line", x="mes",
                              series=[{"field": "y2025", "label": "2025"}, {"field": "y2026", "label": "2026"}],
                              data=[{"mes": "Ene", "y2025": 1, "y2026": 2}])

        assert [s["name"] for s in option["series"]] == ["2025", "2026"]
        assert "legend" in option

    def test_area_and_stacked(self, service):
        option = self._option(service, type="area", stacked=True, x="m", series=["a", "b"],
                              data=[{"m": "Ene", "a": 1, "b": 2}])

        assert all(s["type"] == "line" and "areaStyle" in s and s["stack"] == "total" for s in option["series"])

    def test_lines_never_stack(self, service):
        """A period comparison drawn as stacked lines showed 2026 above 2025 when it
        was lower: the second line was the sum of both (seen in production)."""
        result = service.create_chart(COMPANY, type="line", stacked=True, x="mes",
                                      series=[{"field": "y2025"}, {"field": "y2026"}],
                                      data=[{"mes": "Ene", "y2025": 1261, "y2026": 1000}])

        chart = result[CHART_RESULT_KEY]
        assert all("stack" not in s for s in chart["echarts"]["series"])
        assert chart["stacked"] is False
        assert any("no se apilan" in note for note in result["notes"])

    def test_bars_stack_and_combo_stacks_only_its_bars(self, service):
        bars = self._option(service, type="bar", stacked=True, x="m", series=["a", "b"],
                            data=[{"m": "Ene", "a": 1, "b": 2}])
        combo = self._option(service, type="combo", stacked=True, x="m",
                             series=[{"field": "a", "type": "bar"}, {"field": "b", "type": "bar"},
                                     {"field": "c", "type": "line"}],
                             data=[{"m": "Ene", "a": 1, "b": 2, "c": 3}])

        assert all(s["stack"] == "total" for s in bars["series"])
        assert [s.get("stack") for s in combo["series"]] == ["total", "total", None]

    def test_combo_mixes_bars_and_lines(self, service):
        option = self._option(service, type="combo", x="m",
                              series=[{"field": "ventas"}, {"field": "margen", "type": "line"}],
                              data=[{"m": "Ene", "ventas": 10, "margen": 2}])

        assert [s["type"] for s in option["series"]] == ["bar", "line"]

    def test_pie_has_no_axes(self, service):
        option = self._option(service, type="pie", x="k", series=["v"], data=[{"k": "a", "v": 1}])

        assert "xAxis" not in option
        assert option["series"][0]["type"] == "pie"
        assert option["series"][0]["encode"]["itemName"] == "k"

    def test_scatter_uses_numeric_axes(self, service):
        option = self._option(service, type="scatter", x="edad", series=["monto"],
                              data=[{"edad": 30, "monto": 100}, {"edad": "41", "monto": 80}])

        assert option["xAxis"]["type"] == "value"
        assert option["series"][0]["type"] == "scatter"
        assert option["dataset"]["source"][2] == [41, 80]
