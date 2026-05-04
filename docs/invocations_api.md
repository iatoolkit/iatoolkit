# Referencia API: `POST /<company_short_name>/api/invocations`

Este documento describe el endpoint stateless para integraciones externas.
Está pensado para aplicaciones que necesitan invocar agentes definidos en
IAToolkit o hacer preguntas directas sin depender del historial conversacional.

## Resumen

**Ruta**

```text
POST /<company_short_name>/api/invocations
```

**Objetivo principal**

- Ejecutar una pregunta directa desde una aplicación externa.
- Invocar un agente predefinido usando `agent_name`.
- Enviar opcionalmente `client_data` y archivos adjuntos.
- Ejecutar siempre en modo stateless.


## Autenticación

El endpoint usa el mismo esquema de autenticación que el resto de la API.
Para integraciones externas, el mecanismo esperado es un API key en formato
Bearer.

**Headers requeridos**

```http
Authorization: Bearer <your_api_key>
Content-Type: application/json
```

**Campo requerido en el body para llamadas con API key**

- `user_identifier`

Cuando la autenticación se hace con API key, `user_identifier` debe viajar en
el JSON para que IAToolkit pueda asociar la invocación a un usuario lógico.

## Request Body

### Campos soportados

| Campo | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| `user_identifier` | string | Sí para llamadas con API key | Identificador lógico del usuario final. |
| `agent_name` | string | Condicional | Nombre del agente o prompt a ejecutar. Requerido si no se envía `question`. |
| `question` | string | Condicional | Pregunta directa del usuario. Requerida si no se envía `agent_name`. |
| `model` | string | No | Override explícito del modelo a usar. Si se omite, IAToolkit resuelve el modelo desde el agente o desde la configuración de la compañía. |
| `reasoning_effort` | string | No | Hint opcional de razonamiento. Valores soportados: `minimal`, `low`, `medium`, `high`, `xhigh`. El soporte real depende del provider y del modelo. |
| `client_data` | object | No | Datos estructurados que el agente puede usar al renderizar el prompt. Valor por defecto: `{}`. |
| `files` | array | No | Archivos adjuntos enviados junto a la invocación. Valor por defecto: `[]`. |

### Reglas de validación

- Debe venir al menos uno entre `agent_name` o `question`.
- Si vienen ambos, el prompt puede usar `question` durante su renderizado.
- `reasoning_effort` se aplica en modalidad best-effort. Algunos providers
  pueden ignorarlo.
- El endpoint ignora cualquier intento del cliente de controlar el historial.


## Archivos adjuntos

El formato canónico para adjuntos es:

```json
{
  "files": [
    {
      "filename": "quarterly_report.pdf",
      "base64": "JVBERi0xLjcKJeLjz9MK..."
    }
  ]
}
```

Notas:

- `filename` debe incluir la extensión del archivo.
- `base64` debe contener el contenido del archivo codificado en Base64.
- Los adjuntos son opcionales.
- Imágenes y documentos se procesan de acuerdo con la política runtime de
  adjuntos configurada en el toolkit.


## Ejemplo 1: pregunta directa

```bash
curl -X POST \
  https://your-iatoolkit-instance.com/my_company/api/invocations \
  -H "Authorization: Bearer <your_api_key>" \
  -H "Content-Type: application/json" \
  -d '{
        "user_identifier": "johndoe",
        "question": "¿Cuáles fueron las ventas totales del mes pasado?",
        "reasoning_effort": "medium"
      }'
```

## Ejemplo 2: invocación de agente

```bash
curl -X POST \
  https://your-iatoolkit-instance.com/my_company/api/invocations \
  -H "Authorization: Bearer <your_api_key>" \
  -H "Content-Type: application/json" \
  -d '{
        "user_identifier": "johndoe",
        "agent_name": "get_sales_report",
        "client_data": {
          "region": "North America"
        },
        "reasoning_effort": "high"
      }'
```

## Ejemplo 3: invocación de agente con archivo adjunto

```bash
curl -X POST \
  https://your-iatoolkit-instance.com/my_company/api/invocations \
  -H "Authorization: Bearer <your_api_key>" \
  -H "Content-Type: application/json" \
  -d '{
        "user_identifier": "johndoe",
        "agent_name": "summarize_attached_report",
        "files": [
          {
            "filename": "Q3_Report.pdf",
            "base64": "JVBERi0xLjcKJeLjz9MK..."
          }
        ]
      }'
```

## Forma de la respuesta

El endpoint devuelve el resultado producido por `QueryService`, con una
normalización importante:

- los diagnósticos internos de structured output no se exponen en la respuesta
  pública

Eso significa que campos como `schema_valid`, `schema_errors`, `schema_mode` y
`schema_applied` se eliminan antes de devolver la respuesta.

### Campos comunes de respuesta

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `answer` | string | Respuesta principal en lenguaje natural. |
| `valid_response` | boolean | Indica si la respuesta del modelo fue considerada válida. |
| `response_id` | string | Identificador de respuesta del provider, cuando existe. |
| `additional_data` | object o array o null | Payload estructurado adicional, cuando aplica. |
| `structured_output` | object o null | Structured output generado por el prompt, cuando la definición del prompt lo produce. |

### Ejemplo de respuesta exitosa

```json
{
  "answer": "Las ventas totales del mes pasado fueron $150,000.",
  "response_id": "chatcmpl-yyyyyyyyyyyyyyyyyyyyyy",
  "valid_response": true,
  "additional_data": null,
  "structured_output": null
}
```

## Manejo de errores

### Códigos de estado comunes

| Status | Significado |
| --- | --- |
| `200` | Invocación exitosa. |
| `400` | JSON inválido o body vacío. |
| `401` | Autenticación requerida. |
| `402` | API key inválida o inactiva. |
| `403` | Falta `user_identifier` para auth por API key, o hay mismatch de tenant. |
| `409` | La invocación no pudo ejecutarse por una validación o error de negocio. |
| `500` | Error inesperado del servidor. |

### Ejemplo de respuesta de error

```json
{
  "error": true,
  "error_message": "No se pudo ejecutar la invocacion solicitada."
}
```

El contenido exacto de `error_message` depende de la causa del error.

## Resolución del modelo

Si `model` no se envía, la selección sigue las reglas existentes del toolkit:

- modelo configurado a nivel del agente/prompt, cuando exista
- en caso contrario, modelo default de la compañía

Si `model` se envía en el request, se trata como un override explícito.

## Resumen final

`/api/invocations` es el endpoint recomendado para ejecución externa stateless.
Su contrato cubre los casos de uso principales:

- preguntas directas
- ejecución de agentes/prompts
- `client_data`
- archivos adjuntos
- `reasoning_effort` opcional
