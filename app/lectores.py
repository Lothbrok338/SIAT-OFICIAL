"""Lectura y deteccion de las fuentes del mes. Todo en memoria: nada se escribe a disco."""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from .util import norm, norm_header, to_cents, to_date, to_datetime, to_seconds

RE_LUKA = re.compile(r"\bLUKA\s+([A-Z0-9]{6})\b", re.I)
RE_COD_EST = re.compile(r"\b([A-Z]{3}\d{7})\b")
RE_ORIGINANTE = re.compile(r"Nombre(?:\s+Originante)?\s*:\s*([^.;]+)", re.I)


class ErrorFuente(ValueError):
    """Archivo que no se pudo reconocer o que no tiene las columnas requeridas."""


# ----------------------------------------------------------------- modelos
@dataclass
class Factura:
    nro: object
    fecha: date
    factura: int
    razon: str
    alumno: str
    carrera: str
    nit: object
    bruto: float
    descuento: float
    neto_c: int
    usd: float
    fila: int


@dataclass
class PagoLuka:
    codigo: str
    ref: str
    alumno: str
    descripcion: str
    monto_c: int
    metodo: str            # QR | TARJETA
    f_int: datetime | None
    f_cump: datetime | None
    receptor: str
    exitoso: bool
    fila: int


@dataclass
class Abono:
    asig: str
    fecha: date
    hora_s: int | None
    monto_c: int
    texto: str
    adicionales: str
    originante: str
    caja: str
    luka_code: str | None
    cod_est: str | None
    es_luka: bool
    es_linkser: bool
    fila: int


@dataclass
class Fuente:
    tipo: str               # SINTESIS | LUKA | BANCO | DECISIONES
    nombre: str
    sha256: str
    filas: int = 0
    desde: date | None = None
    hasta: date | None = None
    detalle: dict = field(default_factory=dict)
    advertencias: list[str] = field(default_factory=list)
    registros: list = field(default_factory=list)

    def resumen(self) -> dict:
        return {
            "tipo": self.tipo, "nombre": self.nombre, "sha256": self.sha256, "filas": self.filas,
            "desde": self.desde.isoformat() if self.desde else None,
            "hasta": self.hasta.isoformat() if self.hasta else None,
            "detalle": self.detalle, "advertencias": self.advertencias,
        }


# ----------------------------------------------------------------- utilidades de tabla
def _sheets_xlsx(data: bytes, nombre: str):
    """Devuelve lista de (nombre_hoja, filas) para .xlsx/.xlsm/.xls."""
    low = nombre.lower()
    if low.endswith(".xls") and not low.endswith((".xlsx", ".xlsm")):
        import xlrd  # formato antiguo
        wb = xlrd.open_workbook(file_contents=data)
        out = []
        for sh in wb.sheets():
            rows = []
            for r in range(sh.nrows):
                fila = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        fila.append(xlrd.xldate.xldate_as_datetime(cell.value, wb.datemode))
                    else:
                        fila.append(cell.value)
                rows.append(tuple(fila))
            out.append((sh.name, rows))
        return out
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # archivo corrupto o no es Excel
        raise ErrorFuente(f"{nombre}: no se pudo abrir como Excel ({exc.__class__.__name__}).") from exc
    out = []
    for ws in wb.worksheets:
        out.append((ws.title, [tuple(r) for r in ws.iter_rows(values_only=True)]))
    wb.close()
    return out


def _find_header(rows, required: list[list[str]], max_rows=40):
    """Busca la fila de encabezado que contenga todas las columnas requeridas (alternativas por grupo)."""
    for i, r in enumerate(rows[:max_rows]):
        hs = [norm_header(c) for c in r]
        if all(any(any(alt in h for h in hs) for alt in grupo) for grupo in required):
            return i, hs
    return None, None


def _col(hs: list[str], *alts: str, exact=False) -> int | None:
    for alt in alts:
        for j, h in enumerate(hs):
            if (h == alt) if exact else (alt in h):
                return j
    return None


def _cell(r, j):
    return r[j] if j is not None and j < len(r) else None


# ----------------------------------------------------------------- deteccion
REQ_SINTESIS = [["NDEFACTURA", "FACTURA"], ["IMPORTENETO"]]
REQ_BANCO = [["CREDITOS"], ["CODIGODETRANSACCION", "CODIGODEASIGNACION"]]
REQ_DECISIONES = [["FACTURA"], ["ASIGNACION"], ["MONTOBANCO"], ["DECISIONID"]]


def detectar(nombre: str, data: bytes) -> str:
    low = nombre.lower()
    if low.endswith((".csv", ".txt")):
        texto = _decode(data)
        primera = texto.splitlines()[0] if texto else ""
        h = norm_header(primera)
        if h.startswith("CODIGO") and "FECHADECUMPLIMIENTO" in h:
            return "LUKA"
        raise ErrorFuente(f"{nombre}: el CSV no tiene el encabezado de pagos LUKA (Código, …, Fecha de cumplimiento).")
    if low.endswith((".xlsx", ".xlsm", ".xls")):
        hojas = _sheets_xlsx(data, nombre)
        for titulo, rows in hojas:
            if norm_header(titulo) == "DECISIONES" and _find_header(rows, REQ_DECISIONES)[0] is not None:
                return "DECISIONES"
        for _, rows in hojas:
            if _find_header(rows, REQ_SINTESIS)[0] is not None:
                return "SINTESIS"
        for _, rows in hojas:
            if _find_header(rows, REQ_BANCO)[0] is not None:
                return "BANCO"
        raise ErrorFuente(f"{nombre}: no se reconoce como Síntesis NETVALLE, extracto bancario ni archivo de decisiones.")
    raise ErrorFuente(f"{nombre}: formato no soportado. Usa .xlsx, .xls o .csv.")


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ----------------------------------------------------------------- SINTESIS
def leer_sintesis(nombre: str, data: bytes) -> Fuente:
    hojas = _sheets_xlsx(data, nombre)
    for titulo, rows in hojas:
        h, hs = _find_header(rows, REQ_SINTESIS)
        if h is not None:
            break
    else:
        raise ErrorFuente(f"{nombre}: no se encontró el encabezado de Síntesis (Nº de Factura / Importe Neto).")

    c = {
        "nro": next((j for j in (_col(hs, "NO", exact=True), _col(hs, "N", exact=True), _col(hs, "NRO", exact=True)) if j is not None), 0),
        "fecha": _col(hs, "FECHA"),
        "factura": _col(hs, "NDEFACTURA", "FACTURA"),
        "razon": _col(hs, "NOMBREORAZONSOCIAL", "RAZONSOCIAL"),
        "alumno": _col(hs, "ALUMNO"),
        "carrera": _col(hs, "CARRERA"),
        "nit": _col(hs, "NIT"),
        "bruto": _col(hs, "TOTALBRUTO", "BRUTO"),
        "desc": _col(hs, "DESCUENTO"),
        "neto": _col(hs, "IMPORTENETO"),
        "usd": _col(hs, "MONTOUS", "MONTO"),
    }
    faltan = [k for k in ("fecha", "factura", "alumno", "neto") if c[k] is None]
    if faltan:
        raise ErrorFuente(f"{nombre}: faltan columnas en Síntesis: {', '.join(faltan)}.")

    cabecera = " ".join(norm(x) for r in rows[:h] for x in r if x)
    caja = (re.search(r"CAJA\s+([A-Z0-9]+)", cabecera) or [None, ""])[1]
    fte = Fuente("SINTESIS", nombre, _sha(data), detalle={"hoja": titulo, "caja": caja})
    anuladas = 0
    for i, r in enumerate(rows[h + 1:], start=h + 2):
        fac = _cell(r, c["factura"])
        if fac in (None, ""):
            continue
        try:
            nfac = abs(int(float(fac)))
        except (TypeError, ValueError):
            continue
        neto = to_cents(_cell(r, c["neto"])) or 0
        razon = str(_cell(r, c["razon"]) or "").strip()
        f = to_date(_cell(r, c["fecha"]))
        if neto <= 0 or norm(razon) == "ANULADO" or f is None:
            anuladas += 1
            continue
        fte.registros.append(Factura(
            nro=_cell(r, c["nro"]), fecha=f, factura=nfac, razon=razon,
            alumno=str(_cell(r, c["alumno"]) or "").strip(), carrera=str(_cell(r, c["carrera"]) or "").strip(),
            nit=_cell(r, c["nit"]), bruto=float(to_cents(_cell(r, c["bruto"])) or 0) / 100,
            descuento=float(to_cents(_cell(r, c["desc"])) or 0) / 100, neto_c=neto,
            usd=float(to_cents(_cell(r, c["usd"])) or 0) / 100, fila=i,
        ))
    if not fte.registros:
        raise ErrorFuente(f"{nombre}: no tiene facturas válidas (neto > 0 y no anuladas).")
    dup = {x.factura for x in fte.registros if sum(1 for y in fte.registros if y.factura == x.factura) > 1}
    if dup:
        raise ErrorFuente(f"{nombre}: números de factura repetidos: {', '.join(map(str, sorted(dup))[:10])}.")
    fte.filas = len(fte.registros)
    fte.desde = min(x.fecha for x in fte.registros)
    fte.hasta = max(x.fecha for x in fte.registros)
    fte.detalle.update(anuladas_o_cero=anuladas, total_neto=sum(x.neto_c for x in fte.registros) / 100)
    return fte


# ----------------------------------------------------------------- LUKA
def _parse_luka_rows(texto: str) -> list[list[str]]:
    lineas = texto.splitlines()
    if not lineas:
        return []
    delim = ";" if lineas[0].count(";") > lineas[0].count(",") else ","
    header = next(csv.reader([lineas[0]], delimiter=delim))
    n = len(header)
    out = [header]
    buffer = ""
    for ln in lineas[1:]:
        if not ln.strip() and not buffer:
            continue
        buffer = f"{buffer}\n{ln}" if buffer else ln
        try:
            fila = next(csv.reader([buffer], delimiter=delim, strict=True))
        except csv.Error:
            continue  # comillas abiertas: el registro sigue en la linea siguiente
        if len(fila) == 1 and buffer.startswith('"') and buffer.endswith('"'):
            # Formato LUKA con la fila completa entre comillas
            interno = buffer[1:-1].replace('""', '"')
            fila = next(csv.reader([interno], delimiter=delim))
        if len(fila) < n // 2 and buffer.count('"') % 2 == 1:
            continue
        out.append(fila)
        buffer = ""
    return out


def leer_luka(nombre: str, data: bytes) -> Fuente:
    rows = _parse_luka_rows(_decode(data))
    if len(rows) < 2:
        raise ErrorFuente(f"{nombre}: el CSV de LUKA está vacío.")
    hs = [norm_header(x) for x in rows[0]]
    c = {
        "codigo": _col(hs, "CODIGO", exact=True),
        "estado": _col(hs, "ESTADO", exact=True),
        "desc": _col(hs, "DESCRIPCION"),
        "ref": _col(hs, "REFEMPRESA"),
        "monto": _col(hs, "MONTO", exact=True),
        "f_int": _col(hs, "FECHADEINTENTODEPAGO"),
        "metodo": _col(hs, "METODODEINTENTODEPAGO"),
        "f_cump": _col(hs, "FECHADECUMPLIMIENTO"),
        "e_cump": _col(hs, "ESTADODECUMPLIMIENTO"),
        "receptor": _col(hs, "RECEPTORPERSONALIZADO"),
    }
    faltan = [k for k in ("codigo", "monto", "f_cump", "metodo", "f_int") if c[k] is None]
    if faltan:
        raise ErrorFuente(f"{nombre}: faltan columnas en LUKA: {', '.join(faltan)}.")
    fte = Fuente("LUKA", nombre, _sha(data))
    for i, r in enumerate(rows[1:], start=2):
        cod = str(_cell(r, c["codigo"]) or "").strip().upper()
        if not cod:
            continue
        desc = str(_cell(r, c["desc"]) or "")
        exitoso = norm(_cell(r, c["e_cump"]) or "EXITOSO") == "EXITOSO" and norm(_cell(r, c["estado"]) or "APROBADO") in ("APROBADO", "EXITOSO")
        met = norm(_cell(r, c["metodo"]))
        fte.registros.append(PagoLuka(
            codigo=cod, ref=str(_cell(r, c["ref"]) or "").strip().upper(),
            alumno=desc.split(" - ", 1)[-1].strip() if " - " in desc else desc.strip(), descripcion=desc,
            monto_c=to_cents(_cell(r, c["monto"])) or 0,
            metodo="TARJETA" if met.startswith("TARJETA") else ("QR" if met == "QR" else met),
            f_int=to_datetime(_cell(r, c["f_int"])), f_cump=to_datetime(_cell(r, c["f_cump"])),
            receptor=str(_cell(r, c["receptor"]) or "").strip().upper(), exitoso=exitoso, fila=i,
        ))
    if not fte.registros:
        raise ErrorFuente(f"{nombre}: no se leyeron pagos LUKA.")
    codigos = [p.codigo for p in fte.registros]
    if len(set(codigos)) != len(codigos):
        fte.advertencias.append("El CSV de LUKA tiene códigos repetidos; se usará la primera aparición.")
        vistos, unicos = set(), []
        for p in fte.registros:
            if p.codigo not in vistos:
                vistos.add(p.codigo)
                unicos.append(p)
        fte.registros = unicos
    fechas = [p.f_cump.date() for p in fte.registros if p.f_cump]
    fte.filas = len(fte.registros)
    fte.desde, fte.hasta = (min(fechas), max(fechas)) if fechas else (None, None)
    rec: dict[str, int] = {}
    for p in fte.registros:
        rec[p.receptor or "—"] = rec.get(p.receptor or "—", 0) + 1
    fte.detalle = {
        "exitosos": sum(p.exitoso for p in fte.registros),
        "qr": sum(p.metodo == "QR" for p in fte.registros),
        "tarjeta": sum(p.metodo == "TARJETA" for p in fte.registros),
        "receptores": rec,
    }
    return fte


# ----------------------------------------------------------------- BANCO
def leer_banco(nombre: str, data: bytes) -> Fuente:
    hojas = _sheets_xlsx(data, nombre)
    for titulo, rows in hojas:
        h, hs = _find_header(rows, REQ_BANCO)
        if h is not None:
            break
    else:
        raise ErrorFuente(f"{nombre}: no se encontró el encabezado del extracto (Créditos / Código de transacción).")
    c = {
        "fecha": _col(hs, "FECHA", exact=True) if _col(hs, "FECHA", exact=True) is not None else _col(hs, "FECHA"),
        "hora": _col(hs, "HORA"),
        "asig": _col(hs, "CODIGODETRANSACCION", "CODIGODEASIGNACION"),
        "cred": _col(hs, "CREDITOS"),
        "adic": _col(hs, "ADICIONALES"),
        "caja": _col(hs, "NUMERODECAJA"),
    }
    texto_cols = [j for j, x in enumerate(hs) if any(k in x for k in ("OFICINA", "DESCRIPCION", "REFERENCIA", "GLOSA", "ADICIONALES"))]
    faltan = [k for k in ("fecha", "asig", "cred") if c[k] is None]
    if faltan:
        raise ErrorFuente(f"{nombre}: faltan columnas en el extracto: {', '.join(faltan)}.")
    formato = "CLASIFICADO (Tablas Dinámicas)" if c["caja"] is not None else "EXTRACTO BNB"
    fte = Fuente("BANCO", nombre, _sha(data), detalle={"hoja": titulo, "formato": formato})
    vistos: set[str] = set()
    sin_hora = 0
    for i, r in enumerate(rows[h + 1:], start=h + 2):
        monto = to_cents(_cell(r, c["cred"]))
        if not monto or monto <= 0:
            continue
        f = to_date(_cell(r, c["fecha"]))
        asig = str(_cell(r, c["asig"]) or "").strip()
        if f is None or not asig:
            continue
        if asig in vistos:
            fte.advertencias.append(f"Código de transacción repetido en el extracto: {asig} (se usa la primera fila).")
            continue
        vistos.add(asig)
        adic = str(_cell(r, c["adic"]) or "").strip()
        texto = " ".join(str(_cell(r, j)) for j in texto_cols if _cell(r, j) not in (None, ""))
        caja = norm(_cell(r, c["caja"])) if c["caja"] is not None else ""
        up = texto.upper()
        luka = RE_LUKA.search(adic) or RE_LUKA.search(texto)
        est = RE_COD_EST.search(adic.upper())
        orig = RE_ORIGINANTE.search(adic)
        hora = to_seconds(_cell(r, c["hora"])) if c["hora"] is not None else None
        if hora is None:
            sin_hora += 1
        es_linkser = "LINKSER" in up
        fte.registros.append(Abono(
            asig=asig, fecha=f, hora_s=hora, monto_c=monto, texto=texto, adicionales=adic,
            originante=orig[1].strip() if orig else "", caja=caja,
            luka_code=luka[1].upper() if luka else None, cod_est=est[1] if est else None,
            es_luka=(not es_linkser) and (caja == "HOLALUKA" or "LUKA" in up), es_linkser=es_linkser, fila=i,
        ))
    if not fte.registros:
        raise ErrorFuente(f"{nombre}: el extracto no tiene créditos.")
    fte.filas = len(fte.registros)
    fte.desde = min(a.fecha for a in fte.registros)
    fte.hasta = max(a.fecha for a in fte.registros)
    fte.detalle.update(
        abonos_holaluka=sum(a.es_luka for a in fte.registros),
        abonos_linkser=sum(a.es_linkser for a in fte.registros),
        con_codigo_luka=sum(a.luka_code is not None for a in fte.registros),
    )
    if sin_hora:
        fte.advertencias.append(f"{sin_hora} créditos sin hora: la regla de hora de intento no podrá usarse en ellos.")
    return fte


# ----------------------------------------------------------------- DECISIONES (salida de un mes anterior)
def leer_decisiones(nombre: str, data: bytes) -> Fuente:
    for titulo, rows in _sheets_xlsx(data, nombre):
        if norm_header(titulo) != "DECISIONES":
            continue
        h, hs = _find_header(rows, REQ_DECISIONES)
        if h is None:
            continue
        c = {k: _col(hs, k) for k in ("FACTURA", "ASIGNACION", "FECHABANCO", "MONTOBANCO", "NOTA", "DECISIONID")}
        fte = Fuente("DECISIONES", nombre, _sha(data))
        for r in rows[h + 1:]:
            fac, asig = _cell(r, c["FACTURA"]), _cell(r, c["ASIGNACION"])
            if fac in (None, "") or asig in (None, ""):
                continue
            fte.registros.append({
                "factura": abs(int(float(fac))), "asignacion": str(asig).strip(),
                "fecha_banco": (to_date(_cell(r, c["FECHABANCO"])) or None),
                "monto_banco": (to_cents(_cell(r, c["MONTOBANCO"])) or 0) / 100 or None,
                "nota": str(_cell(r, c["NOTA"]) or ""), "origen": "ARCHIVO",
            })
        fte.filas = len(fte.registros)
        return fte
    raise ErrorFuente(f"{nombre}: no contiene la hoja DECISIONES generada por el conciliador.")


LECTORES = {"SINTESIS": leer_sintesis, "LUKA": leer_luka, "BANCO": leer_banco, "DECISIONES": leer_decisiones}


def leer(nombre: str, data: bytes, tipo_esperado: str | None = None) -> Fuente:
    tipo = detectar(nombre, data)
    if tipo_esperado and tipo != tipo_esperado:
        etiquetas = {"SINTESIS": "Síntesis NETVALLE", "LUKA": "pagos LUKA", "BANCO": "extracto bancario", "DECISIONES": "decisiones"}
        raise ErrorFuente(f"{nombre}: parece {etiquetas[tipo]}, pero se cargó en la casilla de {etiquetas[tipo_esperado]}.")
    return LECTORES[tipo](nombre, data)
