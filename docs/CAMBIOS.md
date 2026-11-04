# Registro de cambios · Comercial reports - Gigafibra

## 4 de noviembre de 2026 · Cards del corte, recaudo, leads TV, descargas y modo oscuro

Publicado en http://10.20.67.35/comercial_reports/. Detalle técnico en [ARQUITECTURA.md](ARQUITECTURA.md) (§5 y §6).

### Cards sobre la tabla

Cuatro cards con su propio filtro de año y mes (por defecto, el último corte; no cambian la tabla):

| Card | Qué muestra | Fuente |
|---|---|---|
| **Suscripciones por segmento** | Gráfico de torta con la participación de cada segmento en el corte (más de 4 → 3 + "Otros") | Tabla del reporte (Active + Past Due Date) |
| **Segmento con más suscripciones** | El segmento líder del mes, variación frente al corte anterior, % del total y tendencia de 12 cortes | Tabla del reporte |
| **Recaudo por plan de TV** | Recaudo efectivo del mes, sin IVA y sin acumular: total del mes y cada plan que recaudó, en pesos completos sin decimales | ERPNext: Payment Entry + Sales Invoice |
| **Leads TV (instalados)** | Leads convertidos (instalados y aprobados) con plan de TV, variación frente al mes anterior, columnas de 12 meses y filtro propio de planes | ERPNext: Lead |

Son **suscripciones en corte**, no ventas.

### Reglas de cálculo

- **Recaudo**: solo pagos con fecha del mes (`Payment Entry` validados, `payment_type = Receive`); de cada pago se toma
  la parte de TV = valor neto de la línea "Canais de TV" × valor aplicado ÷ total de la factura. Un pago anticipado
  (factura emitida después) cuenta en el mes en que entró el dinero. Las notas crédito restan.
- **Plan de cada factura**: corte del mes → corte posterior más cercano → planes actuales de la suscripción → historial
  de cambios (`Version`). Con varios planes de TV, la línea de mayor valor va al plan de mayor costo sin IVA; un plan
  gratis nunca recauda. Sin plan identificable: "Plan no identificado" (a lo sumo 0,17 % de un mes).
- **Leads TV**: leads en estado `Converted` con algún plan de TV del reporte y fecha de activación
  (`custom_activation_date`) en el mes. Con varios planes elegidos en el filtro, cada lead cuenta una vez.
- **Cuándo se calcula**: al arrancar el servicio, cada día a las 06:10 y después de cada corte. Cada mes se recalcula
  hasta 5 días después de cerrar (en el portal aparece como *Provisional*) y luego queda fijo. Se calculan desde 11 meses
  antes del primer corte (enero 2025) hasta el último.

### Verificación con datos reales

- Recaudo: los 22 meses de enero 2025 a octubre 2026 coinciden con una consulta SQL directa a la base de ERPNext (total
  y número de facturas). Ejemplo: septiembre 2026 = $ 39.684.691 en 2.620 facturas.
- El recaudo no sube todos los meses: 16 subidas y 5 bajadas (jun y nov 2025; abr, jun y ago 2026), todas en meses con
  menos facturas pagadas. De $ 17,0 M (ene 2025) a $ 40,9 M (oct 2026).
- Leads convertidos: coinciden mes a mes con `tabLead`.

### Descargas de cada card

Ícono de descarga a la derecha del título de cada card (`/api/descargas/tarjeta/{segmentos|lider|recaudo|leads}`):
Excel con la regla, el origen de los datos, las cifras de la card y el detalle para confirmarlas (cada suscripción del
corte, cada pago con su parte de TV o cada lead), más el `.json` de origen cuando existe. Los meses de dic 2025 a jul
2026 no tienen detalle por suscripción: las cards de segmentos muestran la etiqueta **Excel inicial** y el Excel indica
que son las cantidades de la tabla del Excel inicial del proyecto.

### Peticiones de Postman (colección *ERPNext API*, sufijo "Comercial reports")

| Carpeta | Petición |
|---|---|
| Lead | GET Lista Leads convertidos del mes |
| Payment Entry | GET Lista Payment Entries del mes con facturas |
| Sales Invoice | GET Lista Sales Invoices con planes de TV (líneas Canais de TV) |
| Subscription | GET Lista Subscriptions con planes de TV (plan por suscripción) |
| Subscription | GET Lista Versiones de Subscription con cambios de planes |

Copia de cada petición en `backend/config/consultas_comerciales.json`. Todas son de solo lectura y no piden datos
personales (nombres, teléfonos ni documentos).

### Interfaz

- **Modo oscuro** con el botón *Modo oscuro / Modo claro* de la barra superior. La elección se guarda en el navegador;
  por defecto, modo claro. Paleta de segmentos validada para el fondo oscuro.
- Botón **Descargar Excel** del reporte en el naranja de Gigafibra.

### Backend y operación

- Módulos nuevos: `app/comercial.py` (cálculo de recaudo y leads) y `app/descargas.py` (Excel de cada card).
- Endpoints nuevos: `GET /api/comercial`, `GET /api/descargas/comercial/{AAAA-MM}`,
  `GET /api/descargas/tarjeta/{card}?periodo=AAAA-MM[&plan=…]`.
- Datos por mes en `backend/data/reporte/indicadores/` (`AAAA-MM.json` y `AAAA-MM-detalle.json`; fuera del repositorio).
- Comando de soporte: `python -m scripts.reporte comercial [--periodo AAAA-MM] [--rehacer]`.
- Variables nuevas en `.env` (opcionales): `COMERCIAL_AUTO`, `COMERCIAL_HOUR`, `COMERCIAL_MINUTE`,
  `COMERCIAL_REFRESH_DAYS`.
- Pruebas: 24 (cálculo de recaudo y leads, reparto entre planes, pagos anticipados, descargas por card y API).

## 3 de noviembre de 2026 · Primera versión en producción

- Reporte mensual automático de suscripciones de TV desde ERPNext: corte el último día de cada mes a las 23:50 y Excel
  alimentado sin tocar los meses confirmados.
- Octubre 2026 incluido como corte inicial (consulta del 3 de noviembre).
- Portal con tabla, filtros, historial de cortes y descargas; inicio de sesión con ERPNext.
- Desplegado en 10.20.67.35 (`/var/www/html/Comercial reports`, servicio `comercial-reports`, nginx en
  `/comercial_reports`).
