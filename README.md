# Gigafibra TV Analytics · Reporte mensual de suscripciones de TV

Automatiza el reporte mensual del Excel **planes TV**. Desde noviembre de 2026, **el último día de cada mes a las
23:50 (America/Bogota)** y sin intervención manual:

1. Consulta en **ERPNext API Gigafibra** todas las suscripciones (vista reporte: lead, estrato, ciudad, PPPoE, plan,
   precio), **sin filtro de estado**, una fila por plan. Definición en [backend/config/consulta_postman.json](backend/config/consulta_postman.json).
2. Guarda la respuesta completa como **snapshot `.json`** (`AAAA-MM-DD.json`) con un resumen para curaduría: filas y
   suscripciones por estado, y el conteo del reporte por plan.
3. **Agrega el mes al Excel del año sin tocar lo existente**: hoja nueva con la exportación cruda (p. ej. `30NOV2026`,
   mismas 17 columnas) y columna nueva en `Tabla2` (p. ej. `30-nov`) con la misma fórmula del Excel:
   `=COUNTIFS(hoja!L:L, plan, hoja!D:D, "Active") + COUNTIFS(hoja!L:L, plan, hoja!D:D, "Past Due Date")`.
   Los meses anteriores (dic 2025 – sep 2026) son datos confirmados y quedan **exactamente como en el archivo enviado**.
4. Actualiza la tabla del portal.

**Octubre 2026 (corte inicial)**: no hubo corte el 31 de octubre, así que la consulta del 3 de noviembre de 2026 se
incluyó como corte de octubre: columna `31-oct` en `Tabla2`, hoja cruda `03NOV2026` (fecha real de los datos),
2.786 suscripciones. En *Cortes generados* aparece como "Corte inicial" con su observación.

**Encabezado y hoja**: la columna se titula con el fin del mes que representa (`31-oct`, `30-nov`) y la hoja cruda con
la fecha real en que se tomaron los datos. En un corte normal coinciden; en una recuperación (servidor apagado al
cierre) o en el corte inicial de octubre, la hoja muestra el día real.

**Cambio de año**: el corte del 31 de enero de 2027 crea el libro `planes TV 2027.xlsx` (hoja "Planes TV mensual 2027",
mismos planes, columnas y `Tabla2`) y desde ahí se alimenta ese libro; el de 2026 queda cerrado con diciembre. En el
portal, el filtro de año muestra por defecto el año en curso.

El portal es una sola página: la tabla (planes × cortes, con filtros de año, mes, plan y segmento; cada columna se
titula con mes, año y día de corte), la descarga del Excel y el listado de cortes con sus descargas (`.json` con todos
los estados y Excel) para curaduría. No hay botón para generar cortes: los hace el sistema. Al iniciar sesión se
muestra una animación de carga con el logo (una vez por sesión).

```
backend/
  app/          config, erpnext (consulta), report (corte), xlsx_append (agrega el mes al Excel), scheduler, auth, main
  config/       consulta_postman.json
  scripts/      reporte (inicializar · probar · pendiente · resumen · desarrollo), serve
  tests/        pruebas con un Excel sintético igual al real y ERPNext simulado
  data/reporte/ ← NO borrar (ignorado por git)
    planes TV 2026.xlsx   Excel de 2026 alimentado mes a mes (luego planes TV 2027.xlsx, …)
    snapshots/            consulta completa de cada corte (.json)
    respaldos/            original recibido + Excel previo a cada corte (últimos 3)
    desarrollo/           Excel del corte de prueba (no es el oficial)
    cortes.json · ejecuciones.jsonl · resumen.json
frontend/       React + Vite + TypeScript (una página)
```

## 1. Instalación (Windows)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env        # completar ERPNEXT_API_KEY / ERPNEXT_API_SECRET

cd ..\frontend
npm install
npm run build
```

## 2. Cargar el Excel (una vez)

```powershell
cd backend
.venv\Scripts\python -m scripts.reporte inicializar "C:\Users\...\planes TV 2026 (actualizado septiembre).xlsx" --anio 2026
```

La plataforma trabaja sobre su propia copia (`planes TV 2026.xlsx`); el original queda guardado aparte en `respaldos/`
y nunca se modifica.

## 3. Arrancar

```powershell
backend\.venv\Scripts\python backend\scripts\serve.py --host 0.0.0.0 --port 8010
```

Portal en http://localhost:8010. **El proceso debe quedar encendido**: el corte automático vive dentro de él.

## 4. Cómo se agrega cada mes al Excel

El `.xlsx` es un paquete de partes XML. En cada corte la plataforma copia **byte a byte** todas las partes existentes
(hojas `Subscription`, `30SEP2026` y las de meses anteriores, estilos, textos, tema) y solo:

- agrega la hoja cruda del mes;
- agrega el encabezado y la fórmula (con su valor ya calculado) en la columna siguiente de la hoja del reporte;
- amplía `Tabla2` con la nueva columna calculada;
- registra la hoja en el libro y marca recalcular al abrir.

Verificado con Excel: el libro de 2026 y el de 2027 (simulación nov 2026 → feb 2027) abren sin reparaciones, la tabla se
extiende sola y el recálculo de Excel coincide celda por celda con lo calculado por la plataforma. Antes de cada corte
se respalda el Excel; si algo falla, el archivo queda como estaba.

La descarga se llama **`Planes tv corte AAAA-MM.xlsx`** con el mes del último corte del libro (p. ej.
`Planes tv corte 2026-11.xlsx`). Cada mes agrega ~2,7 MB (la hoja cruda completa).

## 5. Operación y soporte

| Situación | Qué pasa |
|---|---|
| Último día del mes, 23:50 | Corte automático |
| Primer corte de un año nuevo | Se crea el libro de ese año (`planes TV AAAA.xlsx`) |
| Falla de conexión con ERPNext | 3 intentos por solicitud; si el corte falla, nuevo intento cada 30 min (hasta 3) |
| Servidor apagado al cierre | Al arrancar toma el corte pendiente con la fecha real (queda marcado como recuperación) |
| Se ejecuta dos veces el mismo mes | No se duplica: un corte por mes |

Comandos de soporte (desde `backend/`):

```powershell
.venv\Scripts\python -m scripts.reporte probar      # consulta ERPNext y muestra conteos por estado y por plan, sin guardar
.venv\Scripts\python -m scripts.reporte pendiente   # toma el corte solo si hay uno pendiente
.venv\Scripts\python -m scripts.reporte resumen     # recalcula la tabla del portal desde los Excel
.venv\Scripts\python -m scripts.reporte desarrollo  # corte de prueba: .json y Excel aparte, no toca el Excel oficial
```

El corte de prueba aparece en *Cortes generados* con la observación "Corte generado en el desarrollo de la aplicación"
y no ocupa el mes: el corte automático del 30 de noviembre se toma igual.

Para que un `.json` ya guardado cuente como corte de un mes (así se incluyó octubre 2026), sin volver a consultar ERPNext:

```powershell
.venv\Scripts\python -m scripts.reporte incluir 2026-11-03-desarrollo.json --periodo 2026-10 --observacion "Corte de octubre tomado el 3 nov 2026 (generado en el desarrollo de la aplicación)"
```

Si el `.json` era de un corte de prueba, ese registro queda reemplazado por el corte incluido (mismas filas).

**Criterio del reporte**: filas de la consulta con estado `Active` o `Past Due Date` por plan, exactamente como
`COUNTIFS` en el Excel. El `.json` conserva todas las filas y estados para verificarlo.

## 6. Configuración (`backend/.env`)

Ver [backend/.env.example](backend/.env.example). Las credenciales de ERPNext solo viven en el servidor; el navegador
nunca las recibe. En producción: `APP_ENV=production`, `AUTH_MODE=erpnext` y el OAuth Client de ERPNext
(Skip Authorization ✔, Grant Type *Authorization Code*, Redirect URI `https://<host>/api/auth/callback`).

## 7. Pruebas

```powershell
cd backend
.venv\Scripts\python -m pytest -q
```

La versión anterior con dashboard completo está en `respaldo/version-completa-dashboard-2026-11-03.zip`.
