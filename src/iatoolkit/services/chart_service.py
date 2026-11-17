# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""Output charts (BL-025): a chart is something IAToolkit draws, not the model.

The model calls the `iat_chart` system tool with a small schema of IAToolkit's
own (type, x, series, format) and where the numbers come from: a SQL query that
runs here, with the same service and access as `iat_sql_query`, or a few rows
written inline. This service validates that, caps it, and builds the ECharts
option the chat draws. The model never writes ECharts, so a model of any
provider produces the same chart, and the library can change without touching
a prompt.

What goes back to the model is a short summary (rows, series, totals) and the
marker it writes where the chart goes; the chart itself travels with the turn
under `CHART_RESULT_KEY` and never reaches the model's history.
"""

from __future__ import annotations

import datetime
import decimal
import json
import re
import uuid
from typing import Any

from injector import inject

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.sql_service import SqlService

#: The key a chart travels under in a tool result, removed before the result
#: is serialized for the model (like `__native_attachments__`).
CHART_RESULT_KEY = "__iat_chart__"
#: What the model writes, alone on a line, where a chart goes.
CHART_MARKER_RE = re.compile(r"\[\[chart:([a-z0-9]{6,32})\]\]")

CHART_TYPES = ("bar", "line", "area", "pie", "scatter", "combo")
SERIES_TYPES = ("bar", "line", "area")
FORMATS = ("number", "percent", "currency")


def chart_marker(chart_id: str) -> str:
    return f"[[chart:{chart_id}]]"


def _invalid(message: str) -> IAToolkitException:
    return IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER, message)


class ChartService:
    #: Points drawn per chart: more is not readable and weighs on the turn.
    MAX_ROWS = 500
    #: Slices of a pie; the rest are summed into one "Otros" slice.
    MAX_PIE_SLICES = 12
    MAX_SERIES = 12
    #: Up to this many rows go back to the model as they are, so it can write
    #: its conclusion; above it, only per-series totals and extremes.
    ROWS_FOR_MODEL = 40
    OTHERS_LABEL = "Otros"

    _DATE_LIKE = re.compile(r"^\d{4}-\d{2}(-\d{2})?([ T].*)?$")
    _MONTHS = frozenset({
        "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "set", "oct", "nov", "dic",
        "jan", "apr", "aug", "dec",
        "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
        "septiembre", "setiembre", "octubre", "noviembre", "diciembre",
    })

    @inject
    def __init__(self, sql_service: SqlService):
        self.sql_service = sql_service

    # ------------------------------------------------------------------ the tool
    def create_chart(self, company_short_name: str, **kwargs) -> dict:
        """The `iat_chart` handler: a validated chart, and its summary for the model."""
        spec = self._read_spec(kwargs)
        rows, source = self._load_rows(company_short_name, kwargs)
        if not rows:
            raise _invalid("La consulta no devolvió filas: no hay nada que graficar. Dilo al usuario en vez de llamar a iat_chart.")
        columns = self._columns_of(rows)

        x_field = spec["x"]
        if x_field not in columns:
            raise _invalid(
                f"La columna '{x_field}' (x) no está en los datos. Columnas disponibles: {', '.join(columns)}."
            )
        for series in spec["series"]:
            if series["field"] not in columns:
                raise _invalid(
                    f"La columna '{series['field']}' (series) no está en los datos. "
                    f"Columnas disponibles: {', '.join(columns)}."
                )

        chart_type = spec["type"]
        type_suggested = False
        if not chart_type:
            chart_type = self.suggest_type(rows, x_field, len(spec["series"]))
            type_suggested = True

        table = self._build_table(rows, x_field, spec["series"], chart_type)
        notes = []
        total_rows = len(table)
        if chart_type == "pie":
            table, grouped = self._group_pie_slices(table)
            if grouped:
                notes.append(f"Se muestran las {self.MAX_PIE_SLICES - 1} mayores; {grouped} se sumaron en '{self.OTHERS_LABEL}'.")
        elif total_rows > self.MAX_ROWS:
            table = table[:self.MAX_ROWS]
            notes.append(
                f"Se dibujaron las primeras {self.MAX_ROWS} de {total_rows} filas. "
                "Agrega los datos en la consulta para ver el total."
            )

        chart_id = uuid.uuid4().hex[:12]
        header = [x_field] + [series["field"] for series in spec["series"]]
        chart = {
            "id": chart_id,
            "kind": "chart",
            "title": spec["title"],
            "type": chart_type,
            "x": x_field,
            "series": spec["series"],
            "format": spec["format"],
            "stacked": spec["stacked"],
            "columns": header,
            "rows": table,
            "source": source,
            "notes": notes,
        }
        chart["echarts"] = self.build_echarts_option(chart)

        return {
            "status": "ok",
            "chart_id": chart_id,
            "marker": chart_marker(chart_id),
            "type": chart_type,
            "type_suggested": type_suggested,
            "rows": len(table),
            "series": [series["label"] for series in spec["series"]],
            "data": self._data_for_model(header, table, spec["series"]),
            "notes": notes,
            "instructions": (
                f"El gráfico está listo. Escribe {chart_marker(chart_id)} solo en una línea donde debe "
                "aparecer y, después, una o dos frases con la conclusión. No repitas los datos en una "
                "tabla salvo que te la pidan, y no dibujes el gráfico con texto."
            ),
            CHART_RESULT_KEY: chart,
        }

    # ------------------------------------------------------------------ input
    def _read_spec(self, kwargs: dict) -> dict:
        chart_type = str(kwargs.get("type") or "").strip().lower() or None
        if chart_type and chart_type not in CHART_TYPES:
            raise _invalid(f"type debe ser uno de: {', '.join(CHART_TYPES)}.")

        x_field = str(kwargs.get("x") or "").strip()
        if not x_field:
            raise _invalid("Falta x: la columna del eje horizontal (o de las categorías, en una torta).")

        raw_series = kwargs.get("series")
        if isinstance(raw_series, (str, dict)):
            raw_series = [raw_series]
        if not isinstance(raw_series, list) or not raw_series:
            raise _invalid("Falta series: al menos una columna numérica a graficar.")
        if len(raw_series) > self.MAX_SERIES:
            raise _invalid(f"Como máximo {self.MAX_SERIES} series por gráfico.")

        series = []
        for index, item in enumerate(raw_series):
            if isinstance(item, str):
                item = {"field": item}
            if not isinstance(item, dict):
                raise _invalid("Cada serie es un objeto con field (columna) y, opcional, label y type.")
            field = str(item.get("field") or "").strip()
            if not field:
                raise _invalid("Cada serie necesita field: el nombre de la columna numérica.")
            series_type = str(item.get("type") or "").strip().lower() or None
            if series_type and series_type not in SERIES_TYPES:
                raise _invalid(f"El type de una serie debe ser uno de: {', '.join(SERIES_TYPES)}.")
            series.append({
                "field": field,
                "label": str(item.get("label") or "").strip() or field,
                "type": series_type,
            })

        if chart_type == "pie" and len(series) != 1:
            raise _invalid("Una torta lleva exactamente una serie (los valores); x son las categorías.")

        number_format = str(kwargs.get("format") or "number").strip().lower()
        if number_format not in FORMATS:
            raise _invalid(f"format debe ser uno de: {', '.join(FORMATS)}.")

        return {
            "type": chart_type,
            "title": str(kwargs.get("title") or "").strip(),
            "x": x_field,
            "series": series,
            "format": number_format,
            "stacked": bool(kwargs.get("stacked")),
        }

    def _load_rows(self, company_short_name: str, kwargs: dict) -> tuple[list[dict], dict]:
        query = str(kwargs.get("query") or "").strip()
        database_key = str(kwargs.get("database_key") or "").strip()
        data = kwargs.get("data")

        if query or database_key:
            if not (query and database_key):
                raise _invalid("Para graficar desde SQL envía database_key y query juntos.")
            if data:
                raise _invalid("Envía los datos por SQL (database_key + query) o en data, no ambos.")
            # The same service, read-only check and row limit as iat_sql_query; its
            # errors (INVALID_SQL, DATABASE_ERROR) reach the model to correct the query.
            result = self.sql_service.exec_sql(
                company_short_name, database_key=database_key, query=query, format="dict"
            )
            return self._rows_from_sql_result(result), {
                "kind": "sql", "database_key": database_key, "query": query,
            }

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                raise _invalid("data debe ser una lista de objetos (filas), no texto.")
        if not isinstance(data, list) or not data:
            raise _invalid(
                "Faltan los datos: envía database_key y query (preferido: los números salen de la base) "
                "o data como lista de filas."
            )
        if not all(isinstance(row, dict) for row in data):
            raise _invalid("Cada elemento de data es una fila: un objeto columna → valor.")
        return data, {"kind": "inline"}

    @staticmethod
    def _rows_from_sql_result(result: Any) -> list[dict]:
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                raise _invalid("La consulta no devolvió filas en un formato graficable.")
        if isinstance(result, dict):
            for key in ("rows", "data", "result", "results"):
                if isinstance(result.get(key), list):
                    result = result[key]
                    break
        if not isinstance(result, list) or not all(isinstance(row, dict) for row in result):
            raise _invalid("La consulta no devolvió filas en un formato graficable.")
        return result

    @staticmethod
    def _columns_of(rows: list[dict]) -> list[str]:
        columns: list[str] = []
        for row in rows[:50]:
            for key in row.keys():
                if key not in columns:
                    columns.append(str(key))
        return columns

    # ------------------------------------------------------------------ values
    def _build_table(self, rows: list[dict], x_field: str, series: list[dict], chart_type: str) -> list[list]:
        table = []
        for row in rows:
            x_value = self._x_value(row.get(x_field), numeric=(chart_type == "scatter"))
            values = [self._number(row.get(item["field"]), item["field"]) for item in series]
            table.append([x_value] + values)
        return table

    def _x_value(self, value: Any, *, numeric: bool):
        if numeric:
            return self._number(value, "x")
        if value is None:
            return ""
        if isinstance(value, datetime.datetime):
            return value.date().isoformat() if value.time() == datetime.time(0) else value.isoformat(sep=" ")
        if isinstance(value, datetime.date):
            return value.isoformat()
        if isinstance(value, decimal.Decimal):
            return float(value) if value != value.to_integral_value() else int(value)
        return value if isinstance(value, (int, float)) else str(value)

    @staticmethod
    def _number(value: Any, field: str):
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, (float, decimal.Decimal)):
            number = float(value)
            return int(number) if number.is_integer() else round(number, 6)
        if isinstance(value, str):
            text = value.strip().replace(" ", "")
            try:
                number = float(text)
            except ValueError:
                raise _invalid(
                    f"La columna '{field}' tiene un valor no numérico ('{value[:40]}'). "
                    "Las series deben ser números: conviértelos en la consulta."
                )
            return int(number) if number.is_integer() else round(number, 6)
        raise _invalid(f"La columna '{field}' tiene un valor no numérico.")

    def _group_pie_slices(self, table: list[list]) -> tuple[list[list], int]:
        if len(table) <= self.MAX_PIE_SLICES:
            return table, 0
        ordered = sorted(table, key=lambda row: row[1] or 0, reverse=True)
        kept = ordered[:self.MAX_PIE_SLICES - 1]
        rest = ordered[self.MAX_PIE_SLICES - 1:]
        others = sum(row[1] or 0 for row in rest)
        return kept + [[self.OTHERS_LABEL, others]], len(rest)

    def suggest_type(self, rows: list[dict], x_field: str, series_count: int) -> str:
        """Time on x reads best as a line; anything else as bars."""
        values = [row.get(x_field) for row in rows[:50] if row.get(x_field) is not None]
        if values and all(self._is_time_like(value) for value in values):
            return "line" if len(values) > 3 else "bar"
        return "bar"

    def _is_time_like(self, value: Any) -> bool:
        if isinstance(value, (datetime.date, datetime.datetime)):
            return True
        text = str(value).strip().lower()
        return bool(self._DATE_LIKE.match(text)) or text.rstrip(".") in self._MONTHS

    # ------------------------------------------------------------------ the model's view
    def _data_for_model(self, header: list, table: list[list], series: list[dict]):
        """What the model reads to write its conclusion: the rows when few, else a summary."""
        if len(table) <= self.ROWS_FOR_MODEL:
            return {"columns": header, "rows": table}
        summary = {}
        for index, item in enumerate(series, start=1):
            points = [(row[0], row[index]) for row in table if row[index] is not None]
            if not points:
                continue
            low = min(points, key=lambda point: point[1])
            high = max(points, key=lambda point: point[1])
            summary[item["label"]] = {
                "total": round(sum(point[1] for point in points), 6),
                "min": {"x": low[0], "value": low[1]},
                "max": {"x": high[0], "value": high[1]},
                "first": {"x": points[0][0], "value": points[0][1]},
                "last": {"x": points[-1][0], "value": points[-1][1]},
            }
        return {"columns": header, "row_count": len(table), "summary_by_series": summary}

    # ------------------------------------------------------------------ ECharts
    def build_echarts_option(self, chart: dict) -> dict:
        """The ECharts option for a chart: data only, no functions (the chat adds
        number formatting, theme and toolbox when it draws it)."""
        chart_type = chart["type"]
        source = [chart["columns"]] + chart["rows"]
        option: dict[str, Any] = {
            "dataset": {"source": source},
            "tooltip": {"trigger": "item" if chart_type in ("pie", "scatter") else "axis"},
        }
        if chart.get("title"):
            option["title"] = {"text": chart["title"], "left": 0}

        series_defs = chart["series"]
        if chart_type == "pie":
            only = series_defs[0]
            option["legend"] = {"type": "scroll", "bottom": 0}
            option["series"] = [{
                "type": "pie",
                "name": only["label"],
                "radius": ["35%", "65%"],
                "encode": {"itemName": chart["x"], "value": only["field"], "tooltip": only["field"]},
            }]
            return option

        if len(series_defs) > 1:
            option["legend"] = {"type": "scroll", "top": 28 if chart.get("title") else 0}
        option["grid"] = {
            "containLabel": True, "left": 8, "right": 16, "bottom": 8,
            "top": 64 if chart.get("title") and len(series_defs) > 1 else 48,
        }
        option["xAxis"] = {"type": "value" if chart_type == "scatter" else "category", "name": ""}
        option["yAxis"] = {"type": "value"}

        series = []
        for index, item in enumerate(series_defs):
            series_type = self._series_type(chart_type, item, index)
            entry: dict[str, Any] = {
                "type": "line" if series_type == "area" else series_type,
                "name": item["label"],
                "encode": {"x": chart["x"], "y": item["field"]},
            }
            if series_type == "area":
                entry["areaStyle"] = {}
            if chart_type == "scatter":
                entry["type"] = "scatter"
            if chart.get("stacked") and chart_type != "scatter":
                entry["stack"] = "total"
            series.append(entry)
        option["series"] = series
        return option

    @staticmethod
    def _series_type(chart_type: str, item: dict, index: int) -> str:
        if chart_type == "combo":
            return item.get("type") or ("bar" if index == 0 else "line")
        if chart_type in ("bar", "line", "area"):
            return chart_type
        return "scatter"
