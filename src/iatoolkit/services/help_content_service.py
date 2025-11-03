# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.common.util import Utility
from iatoolkit.common.exceptions import IAToolkitException
import os
from injector import inject
import logging


class HelpContentService:
    @inject
    def __init__(self, util: Utility):
        self.util = util

    def get_content(self, company_short_name: str | None) -> dict:
        filepath = f'companies/{company_short_name}/help_content.yaml'
        if not os.path.exists(filepath):
            return {}

        # read the file
        try:
            help_content = self.util.load_schema_from_yaml(filepath)
            return help_content
        except Exception as e:
            logging.exception(e)
            raise IAToolkitException(IAToolkitException.ErrorType.CONFIG_ERROR,
                            f"Error obteniendo help de {company_short_name}: {str(e)}") from e
