"""Libro Excel de salida: asiento SAP, detalle, excepciones, controles y decisiones reutilizables."""
from __future__ import annotations

import io
import re
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .motor import Enlace, Parametros

NAVY = "0B2545"
GOLD = "B08D57"
F_HEAD = PatternFill("solid", fgColor=NAVY)
F_SOFT = PatternFill("solid", fgColor="EEF2F7")
F_CARD = PatternFill("solid", fgColor="FCE4D6")
F_COMM = PatternFill("solid", fgColor="FFF2CC")
F_ADJ = PatternFill("solid", fgColor="E8E0F3")
F_WARN = PatternFill("solid", fgColor="FDECEC")
F_OK = PatternFill("solid", fgColor="E6F4EA")
WHITE_B = Font(bold=True, color="FFFFFF")
THIN = Border(bottom=Side(style="thin", color="D5DCE6"))
MONEY = "#,##0.00"
DATE = "dd/mm/yyyy"

ASIENTO_COLS = ["Nro.", "Fecha", "Nro. de Factura", "Nombre o Razón Social", "Alumno/Participante", "Carrera", "NIT",
                "Total Bruto (Bs.)", "Descuento (Bs.)", "Importe Neto (Bs.)", "Monto ($us.)", "MONTO BANCO/COMISIÓN",
                "ASIGNACIÓN", "DIFERENCIA", "CUENTA CONTABLE", "GLOSA", "OBSERVACIÓN"]


def glosa(p: Parametros, factura: int, alumno: str) -> str:
    s = re.sub(r"\s+", " ", f"{p.prefijo_glosa}{factura} {alumno}".upper()).strip()
    return s[: p.max_glosa]


def asiento_filas(enlaces: list[Enlace], p: Parametros) -> list[dict]:
    filas = []

    def base(e: Enlace):
        f = e.factura
        return [f.nro, f.fecha, f.factura, f.razon, f.alumno, f.carrera, f.nit, f.bruto, f.descuento,
                f.neto_c / 100, f.usd]

    conc = [e for e in enlaces if e.conciliada]
    for e in conc:
        if e.regla == "R4":
            continue
        asig = e.abono.asig if e.abono else getattr(e, "asig_manual", "")
        obs = "QR - CONFIRMADO MANUAL" if e.regla == "M" else "QR"
        if e.diferencia_c and e.ajuste:
            obs += f" · DIFERENCIA Bs {e.diferencia_c/100:,.2f} AJUSTADA EN {e.ajuste['cuenta']}"
        elif e.diferencia_c:
            obs += f" · DIFERENCIA Bs {e.diferencia_c/100:,.2f} REQUIERE AJUSTE"
        filas.append({"tipo": "QR", "valores": base(e) + [e.monto_banco_c / 100, asig, e.diferencia_c / 100,
                                                         p.cuenta_qr, glosa(p, e.factura.factura, e.factura.alumno), obs]})
        if e.diferencia_c and e.ajuste:
            a = e.ajuste
            filas.append({"tipo": "AJUSTE", "valores": base(e) + [abs(e.diferencia_c) / 100, a["asignacion"], 0, a["cuenta"],
                                                                 a["texto"][: p.max_glosa],
                                                                 f"AJUSTE DIFERENCIA ({a['lado']}) F-{e.factura.factura}"]})
    for e in conc:
        if e.regla != "R4":
            continue
        g = glosa(p, e.factura.factura, e.factura.alumno)
        filas.append({"tipo": "TARJETA", "valores": base(e) + [e.monto_banco_c / 100, e.abono.asig, 0, p.cuenta_tarjeta, g,
                                                              "TARJETA - NETO / LOTE LINKSER" if e.lote else "TARJETA - NETO"]})
        filas.append({"tipo": "COMISION", "valores": base(e) + [e.comision_c / 100, f"HOLALUKA-{e.factura.fecha:%m}", 0,
                                                               p.cuenta_comision, g,
                                                               f"TARJETA - COMISION {float(p.comision_tarjeta)*100:.2f}%"]})
    return filas


def _header(ws, row, cols, widths=None):
    for j, c in enumerate(cols, 1):
        cell = ws.cell(row=row, column=j, value=c)
        cell.fill, cell.font = F_HEAD, WHITE_B
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 30
    ws.freeze_panes = ws.cell(row=row + 1, column=1)
    if widths:
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w


def _title(ws, titulo, sub=None):
    ws["A1"] = titulo
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    if sub:
        ws["A2"] = sub
        ws["A2"].font = Font(italic=True, color="5A6B82")


def _fmt(ws, row, cols_money=(), cols_date=()):
    for j in cols_money:
        ws.cell(row=row, column=j).number_format = MONEY
    for j in cols_date:
        ws.cell(row=row, column=j).number_format = DATE


def _d(s):
    if not s:
        return None
    if isinstance(s, (date, datetime)):
        return s
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return s


def construir_excel(res: dict, p: Parametros) -> bytes:
    enlaces: list[Enlace] = res["_enlaces"]
    wb = Workbook()

    # ---------------- RESUMEN
    ws = wb.active
    ws.title = "RESUMEN"
    r = res["resumen"]
    _title(ws, "CONCILIACIÓN HOLALUKA — RESUMEN", f"Período {res['periodo']['desde']} a {res['periodo']['hasta']} · Motor v{res['version']} · Generado {datetime.now():%d/%m/%Y %H:%M}")
    estado = "ASIENTO LIBERABLE" if res["asiento_liberable"] else "ASIENTO NO LIBERADO: " + "; ".join(res["bloqueos"])
    ws["A4"] = estado
    ws["A4"].font = Font(bold=True, color="FFFFFF")
    ws["A4"].fill = PatternFill("solid", fgColor="2E7D4F" if res["asiento_liberable"] else "B3261E")
    ws.merge_cells("A4:D4")
    datos = [
        ("Facturas válidas", r["facturas"], None), ("Conciliadas automáticamente o con decisión", r["conciliadas"], None),
        ("Pendientes (EXCEPCIONES)", r["pendientes"], None), ("% conciliado", r["porcentaje"] / 100, "0.0%"),
        ("Total Síntesis (Bs)", r["total_neto"], MONEY), ("Total conciliado (Bs)", r["total_conciliado"], MONEY),
        ("Total pendiente (Bs)", r["total_pendiente"], MONEY), ("Comisión tarjetas (Bs)", r["comision_tarjetas"], MONEY),
        ("Abonos HOLALUKA del período sin factura", r["abonos_sin_factura_periodo"], None),
        ("Pagos LUKA de la sede sin factura", r["luka_sin_factura"], None),
        ("Receptor LUKA de la sede", res["receptor"] or "—", None),
    ]
    ws["A6"], ws["B6"] = "Indicador", "Valor"
    _header(ws, 6, ["Indicador", "Valor"], [52, 22])
    ws.freeze_panes = None
    for i, (k, v, fmt) in enumerate(datos, 7):
        ws.cell(row=i, column=1, value=k)
        c = ws.cell(row=i, column=2, value=v)
        if fmt:
            c.number_format = fmt
    i += 2
    ws.cell(row=i, column=1, value="Conciliadas por regla").font = Font(bold=True, color=NAVY)
    for k, n in r["por_regla"].items():
        i += 1
        ws.cell(row=i, column=1, value=f"{k} · {res['reglas'][k]}")
        ws.cell(row=i, column=2, value=n)
    if res["advertencias"]:
        i += 2
        ws.cell(row=i, column=1, value="Advertencias").font = Font(bold=True, color="B3261E")
        for a in res["advertencias"]:
            i += 1
            ws.cell(row=i, column=1, value=a).alignment = Alignment(wrap_text=True)

    # ---------------- ASIENTO
    ws = wb.create_sheet("ASIENTO")
    _title(ws, "ASIENTO HOLALUKA — QR PRIMERO / TARJETAS AL FINAL",
           "Cada tarjeta ocupa DOS filas consecutivas: NETO BANCADO y COMISIÓN.")
    ws["A3"] = estado
    ws["A3"].font = Font(bold=True, color="FFFFFF")
    ws["A3"].fill = PatternFill("solid", fgColor="2E7D4F" if res["asiento_liberable"] else "B3261E")
    ws.merge_cells("A3:H3")
    _header(ws, 5, ASIENTO_COLS, [7, 11, 11, 24, 34, 9, 13, 12, 11, 12, 11, 14, 14, 11, 14, 44, 30])
    filas = asiento_filas(enlaces, p)
    for i, fila in enumerate(filas, 6):
        for j, v in enumerate(fila["valores"], 1):
            c = ws.cell(row=i, column=j, value=v)
            if fila["tipo"] == "TARJETA":
                c.fill = F_CARD
            elif fila["tipo"] == "COMISION":
                c.fill = F_COMM
            elif fila["tipo"] == "AJUSTE":
                c.fill = F_ADJ
        ws.cell(row=i, column=13).number_format = "@"
        ws.cell(row=i, column=15).number_format = "@"
        _fmt(ws, i, (8, 9, 10, 11, 12, 14), (2,))
    res["lineas_asiento"] = len(filas)

    # ---------------- CONCILIACION (todas las facturas)
    ws = wb.create_sheet("CONCILIACION")
    cols = ["Factura", "Fecha", "Alumno", "Carrera", "Neto", "Estado", "Regla", "Método", "Código LUKA", "Cód. estudiante",
            "Intento LUKA", "Asignación", "Fecha banco", "Monto banco", "Comisión", "Diferencia", "Lote LINKSER", "Evidencia / motivo"]
    _title(ws, "DETALLE POR FACTURA", "Cada enlace muestra la evidencia que lo respalda.")
    _header(ws, 4, cols, [10, 11, 34, 10, 12, 13, 8, 10, 11, 13, 18, 13, 11, 12, 10, 10, 13, 70])
    todas = sorted(res["conciliadas"] + res["excepciones"], key=lambda x: (x["fecha"], x["factura"]))
    for i, x in enumerate(todas, 5):
        ok = x["regla"] is not None
        vals = [x["factura"], _d(x["fecha"]), x["alumno"], x["carrera"], x["neto"], "CONCILIADA" if ok else "PENDIENTE",
                x["regla"] or "", x["metodo"], x["codigo_luka"], x["codigo_estudiante"], x["intento_luka"], x["asignacion"],
                _d(x["fecha_banco"]), x["monto_banco"], x["comision"], x["diferencia"], x["lote"], x["evidencia"] if ok else x["motivo"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=i, column=j, value=v)
            if not ok:
                c.fill = F_WARN
        _fmt(ws, i, (5, 14, 15, 16), (2, 13))
    ws.auto_filter.ref = f"A4:{get_column_letter(len(cols))}{max(4, 4 + len(todas))}"

    # ---------------- EXCEPCIONES
    ws = wb.create_sheet("EXCEPCIONES")
    cols = ["Factura", "Fecha", "Alumno", "Neto", "Código LUKA", "Motivo", "Propuesta: asignación", "Fecha banco",
            "Monto banco", "Diferencia", "Confianza", "Depositante", "Razón de la propuesta"]
    _title(ws, "EXCEPCIONES — REQUIEREN DECISIÓN",
           "Aprueba en la aplicación o copia la asignación correcta a la hoja DECISIONES y vuelve a cargar este libro.")
    _header(ws, 4, cols, [10, 11, 34, 12, 12, 46, 16, 11, 12, 11, 11, 34, 52])
    i = 5
    for x in res["excepciones"]:
        props = x["propuestas"] or [None]
        for pr in props:
            vals = [x["factura"], _d(x["fecha"]), x["alumno"], x["neto"], x["codigo_luka"], x["motivo"]]
            vals += ([pr["asignacion"], _d(pr["fecha"]), pr["monto"], pr["diferencia"], pr["confianza"], pr["depositante"], pr["motivo"]]
                     if pr else ["— sin candidato —", None, None, None, None, None, "Verifica el depósito en el banco y regístralo como decisión"])
            for j, v in enumerate(vals, 1):
                ws.cell(row=i, column=j, value=v)
            _fmt(ws, i, (4, 9, 10), (2, 8))
            i += 1

    # ---------------- ABONOS SIN FACTURA
    ws = wb.create_sheet("ABONOS SIN FACTURA")
    cols = ["Fecha", "Asignación", "Monto", "Código LUKA", "Depositante", "Clasificación", "En período"]
    _title(ws, "ABONOS HOLALUKA / LINKSER SIN FACTURA ASOCIADA")
    _header(ws, 4, cols, [11, 14, 12, 12, 40, 60, 10])
    for i, a in enumerate(res["abonos_sin_factura"], 5):
        for j, v in enumerate([_d(a["fecha"]), a["asignacion"], a["monto"], a["codigo_luka"], a["depositante"],
                               a["clasificacion"], "SI" if a["en_periodo"] else "NO"], 1):
            c = ws.cell(row=i, column=j, value=v)
            if a["en_periodo"]:
                c.fill = F_WARN
        _fmt(ws, i, (3,), (1,))

    # ---------------- LUKA SIN FACTURA
    ws = wb.create_sheet("LUKA SIN FACTURA")
    cols = ["Código LUKA", "Alumno", "Cód. estudiante", "Monto", "Método", "Cumplimiento", "Receptor", "Asignación en banco"]
    _title(ws, "PAGOS LUKA DE LA SEDE SIN FACTURA EN LA SÍNTESIS", "Pagos cobrados que no tienen factura: verificar emisión o caja.")
    _header(ws, 4, cols, [12, 36, 14, 12, 9, 19, 9, 18])
    for i, x in enumerate(res["luka_sin_factura"], 5):
        for j, v in enumerate([x["codigo"], x["alumno"], x["codigo_estudiante"], x["monto"], x["metodo"],
                               x["fecha_cumplimiento"], x["receptor"], x["asignacion_banco"]], 1):
            ws.cell(row=i, column=j, value=v)
        _fmt(ws, i, (4,))

    # ---------------- CONTROLES
    ws = wb.create_sheet("CONTROLES")
    _title(ws, "CONTROLES DE INTEGRIDAD")
    _header(ws, 4, ["Control", "Valor", "Resultado", "Detalle"], [70, 12, 12, 60])
    for i, c in enumerate(res["controles"], 5):
        for j, v in enumerate([c["control"], c["valor"], "OK" if c["ok"] else "REVISAR", c.get("detalle", "")], 1):
            cell = ws.cell(row=i, column=j, value=v)
            cell.fill = F_OK if c["ok"] else F_WARN

    # ---------------- DECISIONES
    ws = wb.create_sheet("DECISIONES")
    cols = ["Factura", "Asignacion", "Fecha banco", "Monto banco", "Neto factura", "Diferencia", "Nota", "Decision ID",
            "Cuenta ajuste", "Asignacion ajuste", "Texto ajuste"]
    _title(ws, "DECISIONES MANUALES",
           "Para reutilizarlas: agrega filas aquí (Factura + Asignación; Fecha y Monto si el abono no está en el extracto) y carga este libro como 4.º archivo.")
    _header(ws, 4, cols, [10, 16, 12, 12, 12, 11, 50, 14, 14, 16, 30])
    for i, e in enumerate([e for e in enlaces if e.regla == "M"], 5):
        vals = [e.factura.factura, getattr(e, "asig_manual", ""), e.fecha_banco, e.monto_banco_c / 100,
                e.factura.neto_c / 100, e.diferencia_c / 100, e.nota_manual, f"D-{e.factura.factura}",
                (e.ajuste or {}).get("cuenta"), (e.ajuste or {}).get("asignacion"), (e.ajuste or {}).get("texto")]
        for j, v in enumerate(vals, 1):
            ws.cell(row=i, column=j, value=v)
        ws.cell(row=i, column=2).number_format = "@"
        ws.cell(row=i, column=9).number_format = "@"
        _fmt(ws, i, (4, 5, 6), (3,))

    # ---------------- FUENTES
    ws = wb.create_sheet("FUENTES Y PARAMETROS")
    _title(ws, "TRAZABILIDAD", "Huella SHA-256 de cada archivo procesado. Los archivos no se almacenan en el servidor.")
    _header(ws, 4, ["Fuente", "Archivo", "Registros", "Desde", "Hasta", "SHA-256"], [12, 46, 10, 11, 11, 68])
    i = 5
    for f in res["fuentes"]:
        for j, v in enumerate([f["tipo"], f["nombre"], f["filas"], _d(f["desde"]), _d(f["hasta"]), f["sha256"]], 1):
            ws.cell(row=i, column=j, value=v)
        _fmt(ws, i, (), (4, 5))
        i += 1
    i += 1
    ws.cell(row=i, column=1, value="Parámetros").font = Font(bold=True, color=NAVY)
    for k, v in res["parametros"].items():
        i += 1
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=str(v))

    for w in wb.worksheets:
        w.sheet_view.showGridLines = False
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
