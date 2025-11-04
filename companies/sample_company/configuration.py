# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

FUNCTION_LIST = [
        {'name': 'Acceso via SQL a la base de datos.',
         'description': "Debes usar este servicio para consulta sobre Sample Company y sus "
                        "clientes, productos, ordenes , regiones, empleados.",
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
        {'name': 'busquedas en documentos: manuales internos, contratos de trabajo, procedimientos, legales',
         'description': "busquedas sobre documentos: manuales, contratos de trabajo de empleados,"
            'manuales de procedimientos, documentos legales, manuales de proveedores (supply-chain)',
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


PROMPT_LIST = [
            {
                'name': 'analisis_ventas',
                'description': 'Analisis de ventas',
                'order': 1

            },
            {
                'name': 'supplier_report',
                'description': 'Análisis de proveedores',
                'order': 2,
                'custom_fields': [
                    {
                        "data_key": "supplier_id",
                        "label": "Identificador del Proveedor",
                    }
                ]
            },
            {
                'name': 'analisis_despachos',
                'description': 'Analisis de despachos',
                'order': 3,
                'custom_fields': [
                    {
                        "data_key": "init_date",
                        "label": "Fecha desde",
                        "type": "date",
                    },
                    {
                        "data_key": "end_date",
                        "label": "Fecha hasta",
                        "type": "date",
                    }
                ]
            },
        ]

BRANDING = {
    # --- Estilos del Encabezado Principal ---
    "header_background_color": "#4C6A8D",       # Fondo en Azul Acero
    "header_text_color": "#FFFFFF",             # Texto en blanco para un contraste nítido

    "brand_primary_color": "#4C6A8D",           # Azul Acero como color de acción principal
    "brand_secondary_color": "#9EADC0",         # Un gris azulado más claro para acciones secundarias
    "brand_text_on_primary": "#FFFFFF",         # Texto blanco sobre el azul
    "brand_text_on_secondary": "#FFFFFF",       # Texto blanco sobre el gris
}


ONBOARDING_CARDS = [
    {
        'icon': 'fas fa-database',
        'title': 'Sample Company',
        'text': 'Esta una empresa ficticia para mostrarte como interactuar con la IA. Los datos dispobibles son un ejemplo de una empresa '
        'tipica que vende productos, gestiona ordenes de compra, proveedores, empleados y territorios. Se dispone de datos de los años 2024 y 2025.'
    },
    {
        'icon': 'fas fa-database',
        'title': 'Datos disponibles',
        'text': 'Conozco los datos de: clientes, productos, ventas, empleados, territorios, etc..<br><br><strong>Ejemplo:</strong> ¿Cuál fue el producto más vendido en Alemania el año 2024?'
    },
    {
        'icon': 'fas fa-file-alt',
        'title': 'Documentos Internos',
        'text': 'Puedo buscar en manuales internos, contratos de trabajo y documentos legales para encontrar la información que necesitas.<br><br><strong>Ejemplo:</strong> ¿Cuál es el procedimiento para solicitar vacaciones?'
    },
    {
        'icon': 'fas fa-cogs',
        'title': 'Análisis SQL',
        'text': 'Puedes pedirme que ejecute consultas SQL directamente sobre la base de datos y te entregaré los resultados.<br><br><strong>Ejemplo:</strong> "SQL: SELECT * FROM Orders WHERE ShipCountry = \'France\' LIMIT 5"'
    },
    {'icon': 'fas fa-cogs', 'title': 'Personaliza tus Prompts',
     'text': 'Utiliza la varita magica y podras explorar los prompts predefinidos que he preparado para ti.'},
    {'icon': 'fas fa-table', 'title': 'Tablas y Excel',
     'text': 'Puedes pedirme la respuesta en formato de tablas o excel. <br><br><strong>Ejemplo:</strong> dame una tabla con los 10 certificados mas grande este año, columnas: rut, cliente, fecha, monto, tasa, comision, acreedor...'},
    {'icon': 'fas fa-shield-alt', 'title': 'Seguridad y Confidencialidad',
     'text': 'Toda tu información es procesada de forma segura y confidencial dentro de nuestro entorno protegido.'}
]
