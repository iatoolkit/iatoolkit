import abc
from typing import Any, List, Dict, Union

class DatabaseProvider(abc.ABC):
    """
    Abstract interface for interacting with a database source.
    Handles both metadata introspection and query execution.
    """

    # --- Schema Methods ---
    @abc.abstractmethod
    def get_database_structure(self) -> dict:
        """
        Returns the structure of the database (tables, columns, types)
        Format:
        {
            "table_name": {
                "columns": [
                    {"name": "col1", "type": "VARCHAR", "nullable": True, "pk": True},
                    ...
                ]
            }
        }
        """
        pass

    # --- Execution Methods ---
    @abc.abstractmethod
    def execute_query(self, query: str, commit: bool = False) -> Union[List[Dict[str, Any]], Dict[str, int]]:
        """
        Executes a query and returns:
         - A list of dicts for SELECT (rows).
         - A dict {'rowcount': N} for INSERT/UPDATE/DELETE.
        """
        pass

    @abc.abstractmethod
    def commit(self) -> None:
        pass

    @abc.abstractmethod
    def rollback(self) -> None:
        pass