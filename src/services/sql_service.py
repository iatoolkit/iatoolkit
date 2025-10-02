# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from repositories.database_manager import DatabaseManager
from common.util import Utility
from sqlalchemy import text
from injector import inject
import json
from common.exceptions import IAToolkitException


class SqlService:
    @inject
    def __init__(self,util: Utility):
        self.util = util

    def exec_sql(self, db_manager: DatabaseManager, sql_statement: str) -> str:
        """
        Executes a raw SQL statement and returns the result as a JSON string.

        This method takes a DatabaseManager instance and a SQL query, executes it
        against the database, and fetches all results. The results are converted
        into a list of dictionaries, where each dictionary represents a row.
        This list is then serialized to a JSON string.
        If an exception occurs during execution, the transaction is rolled back,
        and a custom IAToolkitException is raised.

        Args:
            db_manager: The DatabaseManager instance to get the database session from.
            sql_statement: The raw SQL statement to be executed.

        Returns:
            A JSON string representing the list of rows returned by the query.
        """
        try:
            # here the SQL is executed
            result = db_manager.get_session().execute(text(sql_statement))

            # get the column names
            cols = result.keys()

            # convert rows to dict
            rows_context = [dict(zip(cols, row)) for row in result.fetchall()]

            # Serialize to JSON with type convertion
            sql_result_json = json.dumps(rows_context, default=self.util.serialize)

            return sql_result_json
        except Exception as e:
            db_manager.get_session().rollback()

            error_message = str(e)
            if 'timed out' in str(e):
                error_message = 'Intentalo de nuevo, se agoto el tiempo de espera'

            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
                                     error_message) from e