# Redshift SQLAlchemy Spike (2026-05-19)

Objetivo: validar una combinacion soportada de `SQLAlchemy` + `sqlalchemy-redshift` para conectar `iatoolkit` a Amazon Redshift usando SQLAlchemy.

## Resultado

Combinacion validada con conexion real e introspeccion:

- `SQLAlchemy==2.0.49`
- `sqlalchemy-redshift==1.0.0`
- `redshift_connector==2.1.14`

Esta combinacion funciono con:

- conexion SQLAlchemy exitosa
- `SELECT current_database(), current_schema()`
- `inspect(engine).get_table_names(schema='public')`

## Combinacion que falla en el estado actual del proyecto

El proyecto hoy usa:

- `SQLAlchemy==2.0.36`
- `psycopg2-binary==2.9.10`

Con `SQLAlchemy==2.0.36` y `sqlalchemy-redshift==1.0.0`, el dialecto no carga. El error observado fue:

```text
ImportError: cannot import name 'DBAPIModule' from 'sqlalchemy.engine.interfaces'
```

Ese fallo aparece tanto con:

- `redshift+psycopg2://...`
- `redshift+redshift_connector://...`

## Hallazgos sobre drivers

### 1. `psycopg2` no sirve para este cluster con estas credenciales

Probado con:

```text
redshift+psycopg2://<user>:<password>@<host>:5439/warehouse?sslmode=require&connect_timeout=10
```

Resultado:

```text
OperationalError: authentication method 13 not supported
```

Conclusion: aunque el dialecto cargue en una version nueva de SQLAlchemy, `psycopg2` sigue fallando contra este cluster/usuario concreto.

### 2. `redshift_connector` si funciona

URI validada:

```text
redshift+redshift_connector://<user>:<password>@<host>:5439/warehouse?sslmode=require
```

Importante: el timeout no debe ir en la query string para esta combinacion porque llega como string al driver y falla con:

```text
TypeError: 'str' object cannot be interpreted as an integer
```

La forma valida fue:

```python
from sqlalchemy import create_engine

engine = create_engine(
    "redshift+redshift_connector://<user>:<password>@<host>:5439/warehouse?sslmode=require",
    pool_pre_ping=True,
    connect_args={"timeout": 10},
)
```

## Recomendacion para `iatoolkit`

Si se quiere soportar Redshift manteniendo SQLAlchemy:

1. Subir `SQLAlchemy` al menos a la combinacion validada `2.0.49`.
2. Anadir dependencias:
   - `sqlalchemy-redshift==1.0.0`
   - `redshift_connector==2.1.14`
3. Usar backend/dialect `redshift+redshift_connector`.
4. Pasar `connect_args={"timeout": 10}` desde `DatabaseManager` en vez de `timeout=10` en el DBURI.
5. No usar `psycopg2` para este origen Redshift concreto porque sigue fallando por autenticacion.

## Conclusiones operativas

- Hay una ruta viable con SQLAlchemy.
- No es viable con la combinacion actual del proyecto.
- La ruta viable para este cluster es `sqlalchemy-redshift` + `redshift_connector`, no `psycopg2`.
