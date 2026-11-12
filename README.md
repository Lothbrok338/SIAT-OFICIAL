# Conciliador HOLALUKA v3

Motor de conciliación mensual de facturas automáticas (Síntesis NETVALLE) contra pagos LUKA y extracto bancario BNB.
**Sin base de datos y sin almacenamiento**: los archivos se procesan en memoria y se descartan; el resultado se descarga en Excel.

## Archivos que se cargan cada mes

| # | Archivo | Período | Formato | Cómo se reconoce |
|---|---------|---------|---------|------------------|
| 1 | **Síntesis NETVALLE** (caja SINTESISCB) | Mes a conciliar (1 al último día) | `.xlsx` | Columnas *Nº de Factura* e *Importe Neto (Bs.)* |
| 2 | **Pagos LUKA** (`luka-pagos-AAAA-MM-01-AAAA-MM-DD.csv`) | El mismo mes completo, todas las sedes | `.csv` | Columnas *Código* y *Fecha de cumplimiento* |
| 3 | **Extracto bancario BNB** | Del 1 del mes **al 5 del mes siguiente** | `.xlsx` / `.xls` (extracto crudo o la hoja *Tablas Dinámicas Profesional*) | Columnas *Código de transacción* y *Créditos* |
| 4 | Decisiones anteriores (opcional) | — | El Excel descargado de una corrida previa | Hoja *DECISIONES* |

El sistema identifica cada archivo por sus columnas: si se carga en la casilla equivocada, lo reubica.

## Reglas de cruce (cadena FACTURA → PAGO LUKA → ABONO)

0. **Factura ↔ LUKA**: fecha de cumplimiento + monto exacto, dentro del receptor de la sede (detectado automáticamente, p. ej. `C` = Cochabamba). Desempate por nombre.
1. **R1** Código LUKA presente en el abono (determinista).
2. **R2** Código estudiantil presente en el abono + monto.
3. **R3** Monto exacto + hora del intento LUKA (±120 s) — transferencias que no traen código (BNB móvil).
4. **R4** Tarjetas: combinación exacta de netos (importe × (1 − 1,40 %)) contra la liquidación LINKSER, ventana de 4 días.
5. **R5** Monto + fecha + evidencia fuerte de nombre del depositante.
- **M** Decisiones manuales: se aplican primero y nunca se reescriben.

Todo enlace exige **unicidad bilateral** (un solo candidato para ambos lados), por lo que el resultado no depende del orden de las filas. Los montos se manejan en centavos enteros. QR solo se cruza contra abonos HOLALUKA; tarjetas solo contra LINKSER. Lo dudoso queda como excepción con propuestas.

El asiento **no se libera** si hay facturas pendientes o diferencias de monto sin ajuste contable (controles en la hoja CONTROLES).

## Salida (Excel)

RESUMEN · ASIENTO (mismas columnas del asiento SAP vigente: QR primero, tarjetas en 2 filas NETO + COMISIÓN) · CONCILIACION (evidencia por factura) · EXCEPCIONES · ABONOS SIN FACTURA · LUKA SIN FACTURA · CONTROLES · DECISIONES · FUENTES Y PARAMETROS (SHA-256 de cada archivo).

## Ejecutar localmente

```bash
pip install -r requirements-dev.txt
pytest -q
uvicorn app.main:app --reload
```

## Despliegue

`Dockerfile` listo para Railway. Variable opcional `ACCESS_KEY`: si se define, la API exige esa clave (la interfaz la solicita una vez por sesión).
