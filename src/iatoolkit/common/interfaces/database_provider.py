import abc
from typing import Any, List, Dict, Union

class DatabaseProvider(abc.ABC):
    """
    Abstract interface for interacting with a database source.
    Handles both metadata introspection and query execution.
    """

    # --- Schema Methods ---
    @abc.abstractmethod
    def get_all_table_names(self) -> List[str]:
        pass

    @abc.abstractmethod
    def get_table_schema(self,
                         table_name: str,
                         db_schema: str,
                         schema_object_name: str | None = None,
                         exclude_columns: List[str] | None = None) -> str:
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