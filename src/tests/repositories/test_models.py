# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from unittest.mock import patch, MagicMock
from iatoolkit.repositories.models import Company, Tool, Document, User, LLMQuery, VSDoc
from sqlalchemy.orm import relationship


class TestModels:
    def setup_method(self):
        self.mock_base = MagicMock()

        # Aquí almacenamos las referencias de los objetos mock retornados
        self.mock_relationship = patch('sqlalchemy.orm.relationship', MagicMock(return_value=relationship)).start()
        self.mock_column = patch('sqlalchemy.Column', MagicMock()).start()
        self.mock_integer = patch('sqlalchemy.Integer', MagicMock()).start()
        self.mock_string = patch('sqlalchemy.String', MagicMock()).start()
        self.mock_float = patch('sqlalchemy.Float', MagicMock()).start()
        self.mock_date_time = patch('sqlalchemy.DateTime', MagicMock()).start()
        self.mock_json = patch('sqlalchemy.JSON', MagicMock()).start()
        self.mock_foreign_key = patch('sqlalchemy.ForeignKey', MagicMock()).start()

        self.model_classes = [Company, Tool, Document, User, LLMQuery, VSDoc]

    def teardown_method(self):
        patch.stopall()

    def test_model_definitions(self):
        for model_class in self.model_classes:
            instance = model_class()  # Asegurarse de que se puedan instanciar correctamente
            instance.to_dict()
            assert instance is not None

    def test_relationship_calls(self):
        # Ahora usamos call_count en el mock generado
        assert self.mock_relationship.call_count == 0
