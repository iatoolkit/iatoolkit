# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

FUNCTION_LIST = [
        {'name': 'Acceso via SQL a la base de datos.',
         'description': "Consultas sobre clientes, productos, ordenes e items de una orden.",
         'function_name': "sql_query",
         'params': {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string",
                                  "description": "string con la consulta en sql"}
                    },
                    "required": ["query"]
                }
         },
        {'name': 'busquedas en la base de datos documental',
         'description': "información de contratos, manuales de procedimiento, etc"
                        "utiliza este servicio cuando no tengas una fuente de contexto clara para responder a la pregunta."
                        "esta es la base documental de la empresa",
         'function_name': "document_search",
         'params': {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string",
                                  "description": "Texto o pregunta a buscar en los documentos."}
                    },
                    "required": ["query"]
                }
         }
    ]
