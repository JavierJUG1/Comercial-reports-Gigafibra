# Gigafibra TV Analytics · Arquitectura (versión simplificada, nov 2026)

Alcance acordado el 3 de noviembre de 2026: **automatizar el reporte mensual del Excel tal como se hacía a mano** y
mostrar una tabla en el portal. La versión con dashboard quedó en `respaldo/version-completa-dashboard-2026-11-03.zip`.

## 1. Reglas del negocio

- Los meses del Excel recibido (dic 2025 – sep 2026) son **datos confirmados**: no se recalculan ni se modifican.
- Desde noviembre de 2026, el **último día de cada mes** el sistema toma el corte de forma **automática** (no hay
  generación manual en el portal).
- El snapshot `.json` guarda **todas las suscripciones, en todos los estados**. El reporte filtra después
  `Active` + `Past Due Date`. Así se puede auditar que la cifra del Excel sale de los datos reales.
- El Excel descargado es el archivo recibido, con los meses nuevos agregados, y se llama `Planes tv corte AAAA-MM.xlsx`
  (mes del último corte).
- **Un libro por año**: el primer corte de 2027 crea `planes TV 2027.xlsx` (mismos planes, columnas y `Tabla2`) y la
  tabla del portal arranca en enero 2027; el filtro de año permite ver los años anteriores.
- La variación entre cortes es siempre la diferencia con el corte anterior (de 0 a 3 es +3).
- **Octubre 2026**: sin corte el 31 de octubre, la consulta del 3-nov-2026 (2.786) se incluyó como corte de octubre
  (`scripts.reporte incluir`): columna `31-oct`, hoja `03NOV2026`, origen "Corte inicial" con observación.
- Encabezado de la columna = fin del mes que representa; nombre de la hoja cruda = fecha real de los datos.
- Un corte de prueba (`scripts.reporte desarrollo`) se lista con la observación "Corte generado en el desarrollo de la
  aplicación", tiene su propio `.json` y Excel en `desarrollo/` y no ocupa el mes ni toca el Excel oficial.

## 2. Fuente: ERPNext API Gigafibra

| | |
|---|---|
| Consulta | `GET /api/resource/Subscription?fields=[…]&limit_page_length=0&order_by=creation desc` (sin filtros) |
| Autenticación | `Authorization: token <api_key>:<api_secret>` (solo en el servidor: `ERPNEXT_API_KEY` / `ERPNEXT_API_SECRET`) |
| Respuesta | Todas las suscripciones, **una fila por plan** (`plans.plan as plan`): ~35.500 filas, ~17 MB, ~3 s |
| Definición | `backend/config/consulta_postman.json` (copia de la petición "GET Lista Subscriptions (vista reporte…)" de la colección *ERPNext API* en Postman, con el mapeo a las 17 columnas del Excel) |

## 3. El corte (`app/report.py`)

1. Ejecuta la consulta (3 intentos con espera creciente ante fallas transitorias).
2. Guarda `snapshots/AAAA-MM-DD.json`: metadatos de la consulta, `curaduria` (filas y suscripciones por estado, conteo
   del reporte por plan y detalle plan × estado) y `data` (todas las filas).
3. Respalda el Excel del año y le agrega el mes con `app/xlsx_append.py`; si es el primer corte del año, crea el libro
   del año con openpyxl (hoja "Planes TV mensual AAAA", `Tabla2`, mismo formato de costo).
4. Registra el corte (`cortes.json`, `ejecuciones.jsonl`) y recalcula `resumen.json` (tabla del portal).

Un corte por mes. El programador (APScheduler, dentro del proceso) dispara `day="last"` a las 23:50; si el servidor
estuvo apagado, al arrancar toma el corte pendiente con la fecha real; si falla, reintenta cada 30 minutos (hasta 3).

## 4. Agregar el mes sin reescribir el Excel (`app/xlsx_append.py`)

Un `.xlsx` es un zip de partes XML. En lugar de abrir y regrabar el libro (lo que reescribiría estilos y metadatos), se
copian **byte a byte** todas las partes existentes y solo se tocan las mínimas:

| Parte | Cambio |
|---|---|
| `xl/worksheets/sheetN.xml` | **Nueva**: hoja cruda del mes (`DDMMMAAAA`), mismas 17 columnas, anchos y formato de fecha de la última hoja cruda |
| Hoja "Planes TV mensual AAAA" | Encabezado `D-mmm` y fórmula `COUNTIFS` (con su valor ya calculado) en la columna siguiente, filas de la tabla |
| `xl/tables/table1.xml` | `Tabla2` se amplía una columna, con su fórmula de columna calculada |
| `xl/workbook.xml`, relaciones, `[Content_Types].xml`, `docProps/app.xml` | Registro de la hoja nueva; recalcular al abrir |
| `xl/calcChain.xml` | Se quita (Excel la regenera) |

Antes de reemplazar el archivo se verifica que el resultado se pueda leer y tenga la hoja y la columna; la escritura es
atómica (archivo temporal y reemplazo final).

**Verificado con el Excel real** (simulación del 30 de noviembre con datos reales): hojas `Subscription` y `30SEP2026`,
estilos, textos compartidos y tema idénticos byte a byte; Excel abre el archivo sin reparar; `Tabla2` pasa a `A1:N15`; el
recálculo de Excel coincide en las 14 celdas con el valor escrito por la plataforma; agosto y septiembre siguen en 2.722 y
2.749 con sus fórmulas. Cada mes agrega ~2,7 MB y ~14 s de proceso.

**Cambio de año verificado** (simulación nov 2026 → feb 2027 sobre una copia): el libro 2026 queda en `A1:O15` con
`30-nov` y `31-dic`; el corte de enero crea `planes TV 2027.xlsx` (`A1:F15`) y febrero lo amplía a `A1:G15`. Ambos
abren en Excel sin reparar y el recálculo coincide con los valores escritos.

## 5. Portal y seguridad

- Una página: último corte, próximo corte automático, origen (ERPNext API Gigafibra), la tabla (filtros de año y mes,
  búsqueda, segmento, variación entre cortes, vista compacta/completa, columna fija) y *Cortes generados* con
  descargas `.json` y Excel.
- Columnas tituladas "Mes Año · día N". Dic 2025 – mar 2026 no traen el día en el Excel: se muestra el fin de mes,
  subrayado como estimado.
- Al iniciar sesión, animación de carga (fondo negro, logo Gigafibra) una vez por sesión del navegador.
- Valores de la tabla: los del Excel (valores fijos y el resultado guardado de cada fórmula).
- Sesión firmada (`HttpOnly`); SSO con ERPNext en producción.
- Las credenciales de ERPNext solo viven en `backend/.env`. El Excel y los `.json` contienen datos de clientes: se
  descargan solo con sesión y `backend/data/` está fuera del repositorio.
