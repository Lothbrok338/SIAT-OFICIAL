"""Relleno de la plantilla maestra SAP S/4HANA "Upload entrada de diario general".

La plantilla se modifica a nivel XML: solo se escriben la fila de cabecera (10) y las posiciones (16+),
se agregan los textos al sharedStrings y un unico estilo de fecha para la columna O. Todo lo demas del
archivo (extension SAP, estilos, anchos, formato condicional, impresora) se copia byte a byte.
"""
from __future__ import annotations

import calendar
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from .motor import Enlace, Parametros

PLANTILLA = Path(__file__).resolve().parent / "plantillas" / "plantilla_sap_maestra.xlsx"
SHEET = "xl/worksheets/sheet1.xml"
EXCEL_EPOCH = date(1899, 12, 30)


class ErrorSAP(ValueError):
    pass


@dataclass
class LineaSAP:
    cuenta: str
    texto: str
    debe_c: int
    haber_c: int
    fecha_valor: date
    asignacion: str
    tipo: str


def _serial(d: date) -> int:
    return (d - EXCEL_EPOCH).days


def _glosa(p: Parametros, factura: int, alumno: str) -> str:
    return re.sub(r"\s+", " ", f"{p.prefijo_glosa}{factura} {alumno}".upper()).strip()[: p.max_glosa]


def construir_lineas(enlaces: list[Enlace], p: Parametros, fin_mes: date) -> list[LineaSAP]:
    conc = [e for e in enlaces if e.conciliada]
    L: list[LineaSAP] = []
    asig = lambda e: e.abono.asig if e.abono else getattr(e, "asig_manual", "")
    # 1) Debe: QR / R1-R5 automaticos
    for e in conc:
        if e.regla not in ("R4", "M"):
            L.append(LineaSAP(p.cuenta_qr, _glosa(p, e.factura.factura, e.factura.alumno), e.monto_banco_c, 0, e.fecha_banco, asig(e), "QR"))
    # 2) Debe: tarjetas (neto + comision)
    for e in conc:
        if e.regla == "R4":
            g = _glosa(p, e.factura.factura, e.factura.alumno)
            L.append(LineaSAP(p.cuenta_tarjeta, g, e.monto_banco_c, 0, e.fecha_banco, e.abono.asig, "TARJETA"))
            L.append(LineaSAP(p.cuenta_comision, g, e.comision_c, 0, e.fecha_banco, f"HOLALUKA-{e.factura.fecha:%m}", "COMISION"))
    # 3) Debe: confirmaciones manuales
    manuales = [e for e in conc if e.regla == "M"]
    for e in manuales:
        L.append(LineaSAP(p.cuenta_qr, _glosa(p, e.factura.factura, e.factura.alumno), e.monto_banco_c, 0, e.fecha_banco, asig(e), "MANUAL"))
    # 4) Haber: recaudacion (total automatico + una linea por factura manual)
    auto_total = sum(e.factura.neto_c for e in conc if e.regla != "M")
    if auto_total:
        L.append(LineaSAP(p.cuenta_recaudacion, p.texto_recaudacion, 0, auto_total, fin_mes, p.asignacion_recaudacion, "RECAUDACION"))
    for e in manuales:
        L.append(LineaSAP(p.cuenta_recaudacion, p.texto_recaudacion, 0, e.factura.neto_c, fin_mes, p.asignacion_recaudacion, "RECAUDACION"))
    # 5) Ajustes de diferencias confirmados
    for e in manuales:
        if e.diferencia_c and e.ajuste:
            monto = abs(e.diferencia_c)
            debe, haber = (0, monto) if e.ajuste["lado"] == "HABER" else (monto, 0)
            L.append(LineaSAP(e.ajuste["cuenta"], e.ajuste["texto"][:50], debe, haber, fin_mes, e.ajuste["asignacion"][:18], "AJUSTE"))
    return L


def validar(lineas: list[LineaSAP], p: Parametros):
    errores = []
    d = sum(x.debe_c for x in lineas)
    h = sum(x.haber_c for x in lineas)
    if d != h:
        errores.append(f"El documento no cuadra: Debe {d/100:,.2f} ≠ Haber {h/100:,.2f}.")
    for i, x in enumerate(lineas, 16):
        if not re.fullmatch(r"\d{1,10}", str(x.cuenta)):
            errores.append(f"Fila {i}: cuenta de mayor inválida '{x.cuenta}'.")
        if len(x.texto) > 50:
            errores.append(f"Fila {i}: texto de posición supera 50 caracteres.")
        if len(x.asignacion) > 18:
            errores.append(f"Fila {i}: asignación supera 18 caracteres.")
        if (x.debe_c > 0) == (x.haber_c > 0):
            errores.append(f"Fila {i}: debe tener importe solo en Debe o solo en Haber.")
        if not x.fecha_valor:
            errores.append(f"Fila {i}: falta fecha valor.")
    for campo, val, mx in (("Sociedad", p.sociedad, 4), ("Tipo de asiento", p.tipo_asiento, 2), ("Centro de beneficio", p.centro_beneficio, 10),
                           ("Texto cabecera", p.texto_cabecera, 25), ("Referencia", p.referencia, 16), ("Moneda", p.moneda, 5)):
        if not val or len(val) > mx:
            errores.append(f"Parámetro {campo} vacío o mayor a {mx} caracteres.")
    if errores:
        raise ErrorSAP(" ".join(errores[:8]))


class _Strings:
    def __init__(self, xml: str):
        self.xml = xml
        self.items = re.findall(r"<si>(.*?)</si>", xml, re.S)
        self.index = {}
        for i, si in enumerate(self.items):
            m = re.fullmatch(r"<t(?: xml:space=\"preserve\")?>(.*?)</t>", si, re.S)
            if m:
                self.index.setdefault(m.group(1), i)
        self.refs = 0
        self.nuevos: list[str] = []

    def id(self, texto: str) -> int:
        self.refs += 1
        key = escape(texto)
        if key not in self.index:
            self.index[key] = len(self.items) + len(self.nuevos)
            attr = ' xml:space="preserve"' if texto != texto.strip() else ""
            self.nuevos.append(f"<si><t{attr}>{key}</t></si>")
        return self.index[key]

    def render(self) -> str:
        m = re.search(r'count="(\d+)" uniqueCount="(\d+)"', self.xml)
        count = int(m.group(1)) + self.refs
        unique = len(self.items) + len(self.nuevos)
        out = self.xml.replace(m.group(0), f'count="{count}" uniqueCount="{unique}"', 1)
        return out.replace("</sst>", "".join(self.nuevos) + "</sst>", 1)


def _agregar_estilo_fecha(styles: str) -> tuple[str, int]:
    """Agrega un xf de fecha (numFmt 14, fuente de datos 11) y devuelve su indice."""
    m = re.search(r'<cellXfs count="(\d+)">', styles)
    n = int(m.group(1))
    xf = '<xf numFmtId="14" fontId="11" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1" applyAlignment="1"><alignment vertical="top"/></xf>'
    styles = styles.replace(m.group(0), f'<cellXfs count="{n + 1}">', 1)
    pos = styles.index("</cellXfs>")
    return styles[:pos] + xf + styles[pos:], n


def _c_str(ref, s, sid):
    return f'<c r="{ref}" s="{s}" t="s"><v>{sid}</v></c>'


def _c_num(ref, s, v):
    return f'<c r="{ref}" s="{s}"><v>{v}</v></c>'


def _num(cents: int) -> str:
    v = cents / 100
    return str(int(v)) if cents % 100 == 0 else f"{v:.2f}"


def generar_plantilla(enlaces: list[Enlace], p: Parametros, periodo_hasta: date) -> tuple[bytes, dict]:
    fin_mes = date(periodo_hasta.year, periodo_hasta.month, calendar.monthrange(periodo_hasta.year, periodo_hasta.month)[1])
    lineas = construir_lineas(enlaces, p, fin_mes)
    if not lineas:
        raise ErrorSAP("No hay líneas para la plantilla SAP.")
    validar(lineas, p)

    zin = zipfile.ZipFile(PLANTILLA)
    sheet = zin.read(SHEET).decode("utf-8")
    strings = _Strings(zin.read("xl/sharedStrings.xml").decode("utf-8"))
    styles, s_fecha = _agregar_estilo_fecha(zin.read("xl/styles.xml").decode("utf-8"))

    # Cabecera (fila 10), estilos de la plantilla maestra
    serial = _serial(fin_mes)
    fila10 = (f'<row r="10" spans="1:25" x14ac:dyDescent="0.25">'
              + _c_str("B10", 2, strings.id(p.sociedad)) + _c_str("C10", 2, strings.id(p.tipo_asiento))
              + _c_num("D10", 11, serial) + _c_num("E10", 11, serial)
              + _c_str("F10", 12, strings.id(f"{fin_mes:%m}")) + _c_str("G10", 13, strings.id(p.texto_cabecera))
              + _c_str("H10", 2, strings.id(p.moneda)) + _c_str("L10", 14, strings.id(p.referencia)) + "</row>")
    sheet, n = re.subn(r'<row r="10"[^>]*>.*?</row>', fila10, sheet, count=1, flags=re.S)
    if n != 1:
        raise ErrorSAP("La plantilla maestra no tiene la fila de cabecera 10 esperada.")

    filas = []
    for i, x in enumerate(lineas, 16):
        cells = _c_str(f"B{i}", 2, strings.id(p.sociedad)) + _c_num(f"C{i}", 2, int(x.cuenta)) + _c_str(f"D{i}", 2, strings.id(x.texto))
        cells += _c_num(f"E{i}", 2, _num(x.debe_c)) if x.debe_c else _c_num(f"F{i}", 2, _num(x.haber_c))
        cells += _c_num(f"L{i}", 2, int(p.centro_beneficio)) if p.centro_beneficio.isdigit() else _c_str(f"L{i}", 2, strings.id(p.centro_beneficio))
        cells += _c_num(f"O{i}", s_fecha, _serial(x.fecha_valor)) + _c_str(f"R{i}", 3, strings.id(x.asignacion))
        filas.append(f'<row r="{i}" spans="2:18" ht="15" customHeight="1" x14ac:dyDescent="0.25">{cells}</row>')
    if re.search(r'<row r="1[6-9]"|<row r="[2-9]\d+"', sheet):
        raise ErrorSAP("La plantilla maestra ya contiene posiciones: usa una plantilla vacía.")
    sheet = sheet.replace("</sheetData>", "".join(filas) + "</sheetData>", 1)
    ultima = 15 + len(lineas)
    sheet = re.sub(r'<dimension ref="[^"]*"/>', f'<dimension ref="A1:Y{ultima}"/>', sheet, count=1)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename == SHEET:
                data = sheet.encode("utf-8")
            elif item.filename == "xl/sharedStrings.xml":
                data = strings.render().encode("utf-8")
            elif item.filename == "xl/styles.xml":
                data = styles.encode("utf-8")
            else:
                data = zin.read(item.filename)
            zout.writestr(item, data)
    resumen = {
        "lineas": len(lineas), "debe": sum(x.debe_c for x in lineas) / 100, "haber": sum(x.haber_c for x in lineas) / 100,
        "fecha_contabilizacion": fin_mes.isoformat(),
        "por_tipo": {t: sum(1 for x in lineas if x.tipo == t) for t in dict.fromkeys(x.tipo for x in lineas)},
    }
    return out.getvalue(), resumen
