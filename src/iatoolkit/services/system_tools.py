SYSTEM_TOOLS_DEFINITIONS = [
    {
        "function_name": "iat_generate_excel",
        "description": "Generador de Excel."
                       "Genera un archivo Excel (.xlsx) a partir de una lista de diccionarios. "
                       "Cada diccionario representa una fila del archivo. "
                       "el archivo se guarda en storage."
                       "retorna diccionario con filename y attachment_token (para recuperar el archivo)"
                       "content_type y download_link",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Nombre del archivo de salida (ejemplo: 'reporte.xlsx')",
                    "pattern": "^.+\\.xlsx?$"
                },
                "sheet_name": {
                    "type": "string",
                    "description": "Nombre de la hoja dentro del Excel",
                    "minLength": 1
                },
                "data": {
                    "type": "array",
                    "description": "Lista de diccionarios. Cada diccionario representa una fila.",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "number"},
                                {"type": "boolean"},
                                {"type": "null"},
                                {
                                    "type": "string",
                                    "format": "date"
                                }
                            ]
                        }
                    }
                }
            },
            "required": ["filename", "sheet_name", "data"]
        }
    },
    {
        'function_name': "iat_send_email",
        'description': "iatoolkit mail system. "
                       "envia mails cuando un usuario lo solicita.",
        'parameters': {
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": "email del destinatario"},
                "subject": {"type": "string", "description": "asunto del email"},
                "body": {"type": "string", "description": "HTML del email"},
                "attachments": {
                    "type": "array",
                    "description": "Lista de archivos adjuntos codificados en base64",
                    "items": {
                        "type": "object",
                        "properties": {
                            "filename": {
                                "type": "string",
                                "description": "Nombre del archivo con su extensión (ej. informe.pdf)"
                            },
                            "content": {
                                "type": "string",
                                "description": "Contenido del archivo en b64."
                            },
                            "attachment_token": {
                                "type": "string",
                                "description": "token para descargar el archivo."
                            }
                        },
                        "required": ["filename", "content", "attachment_token"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["recipient", "subject", "body", "attachments"]
        }
    },
    {
        "function_name": "iat_sql_query",
        "description": "Servicio SQL de IAToolkit: debes utilizar este servicio para todas las consultas SQL a bases de datos.",
        "parameters": {
            "type": "object",
            "properties": {
                "database_key": {
                    "type": "string",
                    "description": "IMPORTANT: nombre de la base de datos a consultar."
                },
                "query": {
                    "type": "string",
                    "description": "string con la consulta en sql"
                },
            },
            "required": ["database_key", "query"]
        }
    },
    {
        "function_name": "iat_document_search",
        "description": "Búsqueda semantica sobre los documentos que forman una colección",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto o pregunta a buscar en los documentos."
                },
                "collection": {
                    "type": "string",
                    "description": "Opcional. Nombre de la colección donde buscar (ej: 'Planos', 'Marketing')."
                },
                "metadata_filter": {
                    "type": "array",
                    "description": "Opcional. Filtros de metadata como lista de pares key/value. Ejemplo: [{'key':'doc.type','value':'invoice'},{'key':'chunk.source_type','value':'table'}].",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Clave del filtro (ej: doc.type, chunk.source_type, image.page)."
                            },
                            "value": {
                                "anyOf": [
                                    {"type": "string"},
                                    {"type": "number"},
                                    {"type": "boolean"},
                                    {"type": "null"}
                                ],
                                "description": "Valor escalar del filtro."
                            }
                        },
                        "required": ["key", "value"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["query", "collection", "metadata_filter"]
        }
    },
    {
        "function_name": "iat_image_search",
        "description": "Busca imágenes en la base de conocimiento visual de la empresa usando una descripción de texto. "
                       "Útil cuando el usuario pide 'ver' algo, 'muéstrame una foto de...', o busca gráficos y diagramas."
                    "",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Descripción detallada de la imagen que se busca (ej: 'foto de la fachada del edificio')."
                },
                "collection": {
                    "type": "string",
                    "description": "Opcional. Nombre de la colección donde buscar (ej: 'Planos', 'Marketing')."
                },
                "metadata_filter": {
                    "type": "array",
                    "description": "Opcional. Filtros de metadata como lista de pares key/value. Ejemplo: [{'key':'doc.type','value':'invoice'},{'key':'image.page','value':1}].",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Clave del filtro (ej: doc.type, image.page, image.caption_text)."
                            },
                            "value": {
                                "anyOf": [
                                    {"type": "string"},
                                    {"type": "number"},
                                    {"type": "boolean"},
                                    {"type": "null"}
                                ],
                                "description": "Valor escalar del filtro."
                            }
                        },
                        "required": ["key", "value"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["query", "collection", "metadata_filter"]
        }
    },
    {
        "function_name": "iat_visual_search",
        "description": "Busca imágenes visualmente similares a una imagen adjunta por el usuario (búsqueda por similitud visual). "
                       "Si el usuario adjunta una imagen y solicita buscar algo similar debes utilizar este servicio.",
        "parameters": {
            "type": "object",
            "properties": {
                "image_index": {
                    "type": "integer",
                    "description": "Opcional. Índice (0-based) de la imagen adjunta a usar. Por defecto es 0 (la primera imagen)."
                },
                "n_results": {
                    "type": "integer",
                    "description": "Cantidad de resultados a devolver (por defecto 3).",
                    "minimum": 1,
                    "maximum": 5
                },
                "collection": {
                    "type": "string",
                    "description": "Opcional. Nombre de la colección donde buscar (ej: 'Planos', 'Marketing')."
                },
                "metadata_filter": {
                    "type": "array",
                    "description": "Opcional. Filtros de metadata como lista de pares key/value. Ejemplo: [{'key':'doc.type','value':'invoice'},{'key':'image.caption_text','value':'logo'}].",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Clave del filtro (ej: doc.type, image.caption_text)."
                            },
                            "value": {
                                "anyOf": [
                                    {"type": "string"},
                                    {"type": "number"},
                                    {"type": "boolean"},
                                    {"type": "null"}
                                ],
                                "description": "Valor escalar del filtro."
                            }
                        },
                        "required": ["key", "value"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["n_results", "image_index", "collection",  "metadata_filter"]
        }
    },
    {
        "function_name": "iat_web_search",
        "description": "Realiza una búsqueda web externa para obtener información pública actualizada.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto de búsqueda."
                }
            },
            "required": ["query"]
        }
    },
]
