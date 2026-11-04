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
- Dos cards de segmentos, con su propio filtro de año y mes (por defecto, el último corte; no cambian la tabla):
  *Suscripciones por segmento* (gráfico de torta con la participación de cada segmento en el corte; más de 4
  segmentos → 3 + "Otros") y *Segmento con más suscripciones* (titulado solo con el mes del corte: valor, variación
  frente al corte anterior, % del total, tendencia de hasta 12 cortes y el segmento que más creció). Son suscripciones
  en corte (Active + Past Due Date), no ventas.
- Dos cards comerciales con el mismo filtro (ver §6): *Recaudo por plan de TV* (recaudo efectivo del mes sin IVA, sin
  acumular: total del mes, variación frente al mes anterior y una fila por cada plan que recaudó con el color del
  segmento del plan; valores en pesos completos sin decimales) y *Leads TV (instalados)* (leads convertidos con plan de
  TV del mes, variación frente al mes anterior y columnas de 12 meses; filtro propio de planes de TV).
- Cada card tiene un ícono de descarga (`/api/descargas/tarjeta/{segmentos|lider|recaudo|leads}?periodo=AAAA-MM`,
  `app/descargas.py`): Excel con las cifras de la card, la regla, el origen y el detalle para confirmarlas (suscripciones
  del corte, pagos con su parte de TV o leads), y el `.json` de origen cuando existe. Los meses sin detalle por
  suscripción (dic 2025 – jul 2026) llevan la etiqueta *Excel inicial*: son las cantidades de la tabla del Excel inicial
  del proyecto, y el Excel descargado lo indica.
- El botón *Descargar Excel* del reporte usa el naranja de Gigafibra.
- Modo oscuro: botón *Modo oscuro / Modo claro* en la barra superior (en móvil, solo el ícono). La elección se guarda
  en el navegador (`localStorage`, clave `tva_tema`) y se aplica antes de pintar la página (script en `index.html`);
  por defecto, modo claro. Los colores viven en `styles/tokens.css` (`:root` y `:root[data-theme="dark"]`); la paleta
  de segmentos usa en oscuro los mismos ocho tonos con sus pasos para fondo oscuro, validados contra `#18181b`
  (banda de luminosidad, separación con daltonismo y contraste ≥ 3:1).
- Columnas tituladas "Mes Año · día N". Dic 2025 – mar 2026 no traen el día en el Excel: se muestra el fin de mes,
  subrayado como estimado.
- Al iniciar sesión, animación de carga (fondo negro, logo Gigafibra) una vez por sesión del navegador.
- Valores de la tabla: los del Excel (valores fijos y el resultado guardado de cada fórmula).
- Sesión firmada (`HttpOnly`); SSO con ERPNext en producción.
- Las credenciales de ERPNext solo viven en `backend/.env`. El Excel y los `.json` contienen datos de clientes: se
  descargan solo con sesión y `backend/data/` está fuera del repositorio.

## 6. Cards comerciales (`app/comercial.py`)

Peticiones GET de la colección *ERPNext API* de Postman (sufijo "Comercial reports"), copiadas en
`backend/config/consultas_comerciales.json`; el backend reemplaza fechas, planes y suscripciones en los marcadores.

| Petición (carpeta) | Para qué |
|---|---|
| GET Lista Leads convertidos del mes (Lead) | `status = Converted` y `custom_activation_date` dentro del mes; una fila por plan (`custom_planos`) |
| GET Lista Payment Entries del mes con facturas (Payment Entry) | `docstatus = 1`, `payment_type = Receive`, `posting_date` en el mes; una fila por factura aplicada |
| GET Lista Sales Invoices con planes de TV (Sales Invoice) | líneas `Canais de TV` de facturas validadas emitidas desde 12 meses antes del mes hasta hoy (incluye pagos anticipados) |
| GET Lista Subscriptions con planes de TV (Subscription) | planes de TV actuales de cada suscripción, con su orden (`plans.idx`) |
| GET Lista Versiones de Subscription con cambios de planes (Subscription) | historial (`Version`) de suscripciones que ya no tienen TV, en lotes de 100 |

**Leads TV (instalados)**: leads distintos con alguno de los planes de la tabla del reporte. Se guardan también las
combinaciones de planes de TV por lead (`combinaciones_tv`), para que el filtro de planes cuente cada lead una vez.

**Recaudo por plan de TV** (recaudo efectivo del mes, sin IVA): cada mes cuenta solo los pagos con `posting_date` en
ese mes; no se acumula (septiembre = lo que entró del 1 al 30 de septiembre), aunque la factura sea de un mes
anterior o posterior (pago anticipado). Por cada pago a una factura con TV,
`recaudo = net_amount de la línea de TV × allocated_amount ÷ total de la factura (rounded_total o grand_total)`. Las
notas crédito restan. El plan de cada línea:

1. corte del mes (snapshot `.json` o hoja cruda del Excel: agosto, septiembre y octubre de 2026 en adelante);
2. corte posterior más cercano (meses sin hoja cruda);
3. planes actuales de la suscripción;
4. historial: planes de TV quitados o reemplazados en o después de la fecha de la factura (también cuando 1–3 solo
   muestran un plan gratis: el plan pagado que tenía al facturar);
5. "Plan no identificado" (en ene 2025 – oct 2026, a lo sumo el 0,17 % del recaudo de un mes).

Con un plan de TV, todas sus líneas van a ese plan. Con varios (p. ej. "TV + 1 SetBox" y "TV - Free"), la línea de
mayor valor va al plan de mayor "Costo sin IVA" del Excel y las de $ 0 a los gratis; a igual costo, la k-ésima línea va
al k-ésimo plan de la tabla de planes. Un plan gratis nunca recauda: una línea con valor que solo cae en planes gratis
queda como "Plan no identificado".

Verificado contra la base: los 22 meses de ene 2025 a oct 2026 coinciden con SQL directo (mismo total y mismas
facturas; p. ej. agosto 2026 = $ 38.046.416 y 2.593 facturas); los leads coinciden mes a mes con `tabLead`. El
recaudo no sube todos los meses: de ene 2025 a oct 2026 hubo 16 subidas y 5 bajadas (jun y nov 2025; abr, jun y ago
2026), todas en meses con menos facturas pagadas.

**Cuándo se calcula**: al arrancar y cada día a las 06:10 (`COMERCIAL_AUTO`), y después de cada corte. Se calculan
desde 11 meses antes del primer corte hasta el último corte (tendencia de 12 meses completa). Un mes se recalcula
hasta 5 días después de cerrar (`COMERCIAL_REFRESH_DAYS`) y luego queda fijo. Se guarda en `data/reporte/indicadores/`:
`AAAA-MM.json` (resumen que lee el portal) y `AAAA-MM-detalle.json` (peticiones con sus parámetros, leads y pagos con
la parte de TV y de dónde salió el plan), que se descarga desde la card. Sin datos personales (no se piden nombres,
teléfonos ni documentos).
