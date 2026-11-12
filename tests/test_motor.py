"""Pruebas del motor con casos sinteticos que reproducen situaciones reales observadas."""
import csv
import io
import random
from datetime import date, datetime

import openpyxl
import pytest

from app.excel import asiento_filas, construir_excel
from app.lectores import Abono, Factura, Fuente, PagoLuka, leer
from app.motor import Conciliador, Parametros, conciliar

D = date(2026, 10, 7)


def fac(n, neto, alumno, d=D):
    return Factura(nro=n, fecha=d, factura=16000 + n, razon=alumno.split()[0], alumno=alumno, carrera="MED", nit=1,
                   bruto=neto, descuento=0, neto_c=int(neto * 100), usd=neto, fila=n)


def pago(cod, neto, alumno, intento, cumple=None, metodo="QR", rec="C", ref="ABC1234567"):
    return PagoLuka(codigo=cod, ref=ref, alumno=alumno, descripcion=f"Colegiatura - {alumno}", monto_c=int(neto * 100),
                    metodo=metodo, f_int=intento, f_cump=cumple or intento, receptor=rec, exitoso=True, fila=1)


def abono(asig, neto, d, hora=None, luka=None, adic="", linkser=False, es_luka=True):
    return Abono(asig=asig, fecha=d, hora_s=hora, monto_c=int(round(neto * 100)), texto=adic, adicionales=adic,
                 originante=adic, caja="", luka_code=luka, cod_est=None, es_luka=es_luka and not linkser,
                 es_linkser=linkser, fila=1)


def fuentes(fs, ps, abs_):
    return Fuente("SINTESIS", "s", "x", registros=fs), Fuente("LUKA", "l", "x", registros=ps), Fuente("BANCO", "b", "x", registros=abs_)


def run(fs, ps, abs_, dec=None, p=None):
    return conciliar(*fuentes(fs, ps, abs_), dec, p)


def by_fac(res):
    return {x["factura"]: x for x in res["conciliadas"] + res["excepciones"]}


def test_r1_codigo_luka():
    t = datetime(2026, 10, 7, 10, 0, 0)
    r = run([fac(1, 784, "PEREZ ROCA ANA LUCIA")], [pago("AAA111", 784, "Ana Lucia Perez Roca", t)],
            [abono("3P1", 784, D, 36000, luka="AAA111")])
    x = by_fac(r)[16001]
    assert x["regla"] == "R1" and x["asignacion"] == "3P1"
    assert r["asiento_liberable"]


def test_pago_intentado_un_dia_y_cumplido_otro():
    """Caso real anonimizado: banco = dia del intento, factura = dia del cumplimiento."""
    intento = datetime(2026, 10, 6, 18, 0, 0)
    cumple = datetime(2026, 10, 7, 8, 0, 0)
    r = run([fac(1, 10224, "QUIROGA VELARDE SOFIA ELENA")],
            [pago("BBB222", 10224, "Sofia Elena Quiroga Velarde", intento, cumple)],
            [abono("3P9", 10224, date(2026, 10, 6), 18 * 3600 - 48, adic="Nombre: VELRDE ELENA")])
    assert by_fac(r)[16001]["regla"] == "R3"


def test_tercero_paga_hermano_por_hora():
    """Caso real anonimizado: el depositante es otra persona; la hora del intento identifica el abono."""
    t1, t2 = datetime(2026, 10, 7, 11, 0, 0), datetime(2026, 10, 7, 11, 4, 0)
    fs = [fac(1, 3626, "MENDEZ ARCE LUIS FERNANDO"), fac(2, 2437, "MENDEZ ARCE TOMAS ANDRES")]
    ps = [pago("A1", 3626, "Luis Mendez", t1), pago("A2", 2437, "Tomas Mendez", t2)]
    ab = [abono("3PA", 3626, D, 11 * 3600 - 6, adic="LUIS FERNANDO MENDE"), abono("3PB", 2437, D, 11 * 3600 + 240 - 5, adic="LUIS FERNANDO MENDE")]
    r = by_fac(run(fs, ps, ab))
    assert r[16001]["asignacion"] == "3PA" and r[16002]["asignacion"] == "3PB"


def test_r3_no_toma_abono_con_otro_codigo_luka():
    t = datetime(2026, 10, 7, 10, 0, 0)
    r = run([fac(1, 500, "PEREZ ANA")], [pago("AAA111", 500, "Ana Perez", t)],
            [abono("3P1", 500, D, 36000 - 3, luka="ZZZ999")])
    assert by_fac(r)[16001]["regla"] is None


def test_ambiguo_no_se_adivina():
    """Dos abonos identicos en monto y hora: no se elige ninguno."""
    t = datetime(2026, 10, 7, 10, 0, 0)
    r = run([fac(1, 500, "PEREZ ANA")], [pago("AAA111", 500, "Ana Perez", t)],
            [abono("3P1", 500, D, 36000 - 3), abono("3P2", 500, D, 36000 - 10)])
    x = by_fac(r)[16001]
    assert x["regla"] is None and len(x["propuestas"]) == 2


def test_desempate_factura_luka_por_nombre():
    t1, t2 = datetime(2026, 10, 7, 9, 0, 0), datetime(2026, 10, 7, 15, 0, 0)
    fs = [fac(1, 1000, "ROJAS LIMA JUAN"), fac(2, 1000, "QUISPE MAMANI ROSA")]
    ps = [pago("P1", 1000, "Rosa Quispe Mamani", t1), pago("P2", 1000, "Juan Rojas Lima", t2)]
    ab = [abono("3P1", 1000, D, luka="P1"), abono("3P2", 1000, D, luka="P2")]
    r = by_fac(run(fs, ps, ab))
    assert r[16001]["codigo_luka"] == "P2" and r[16002]["codigo_luka"] == "P1"


def test_receptor_de_otra_sede_no_se_usa():
    t = datetime(2026, 10, 7, 10, 0, 0)
    fs = [fac(i, 100 * i, f"ALUMNO {i}") for i in range(1, 6)]
    ps = [pago(f"C{i}", 100 * i, "x", t, rec="C") for i in range(1, 6)]
    ab = [abono(f"3P{i}", 100 * i, D, luka=f"C{i}") for i in range(1, 6)]
    fs.append(fac(9, 900, "G H I"))
    ps.append(pago("L1", 900, "z", t, rec="L"))
    ab.append(abono("3P9", 900, D, luka="L1"))
    r = run(fs, ps, ab)
    assert r["receptor"] == "C"
    assert by_fac(r)[16009]["codigo_luka"] is None  # el pago de La Paz no se enlaza a una factura de Cochabamba
    assert any("otra sede" in a["clasificacion"] for a in r["abonos_sin_factura"])


def test_lote_linkser_dos_tarjetas():
    t = datetime(2026, 10, 7, 10, 0, 0)
    fs = [fac(1, 930, "ROJAS PABLO"), fac(2, 2892, "VARGAS LUCIA")]
    ps = [pago("T1", 930, "Diego", t, metodo="TARJETA"), pago("T2", 2892, "Isabel", t, metodo="TARJETA")]
    total = 916.98 + 2851.51
    r = run(fs, ps, [abono("3PL", total, date(2026, 10, 9), linkser=True)])
    x = by_fac(r)
    assert x[16001]["regla"] == "R4" and x[16001]["lote"] == "3PL" and x[16001]["comision"] == pytest.approx(13.02)
    assert x[16002]["monto_banco"] == pytest.approx(2851.51) and x[16002]["comision"] == pytest.approx(40.49)
    assert all(c["ok"] for c in r["controles"][:4])


def test_tarjeta_fuera_de_ventana_no_concilia():
    t = datetime(2026, 10, 1, 10, 0, 0)
    r = run([fac(1, 930, "X Y Z", date(2026, 10, 1))], [pago("T1", 930, "x", t, metodo="TARJETA")],
            [abono("3PL", 916.98, date(2026, 10, 9), linkser=True)])
    assert by_fac(r)[16001]["regla"] is None


def test_codigo_con_monto_distinto_y_decision():
    """Caso real anonimizado: banco 1107, factura 1106."""
    t = datetime(2026, 10, 2, 15, 16, 31)
    fs = [fac(1, 1106, "SALAZAR VEGA MARCO ANTONIO", date(2026, 10, 8))]
    ps = [pago("CCC333", 1106, "Marco Antonio Salazar Vega", t, datetime(2026, 10, 8, 8, 49))]
    ab = [abono("3P00000099", 1107, date(2026, 10, 2), luka="CCC333")]
    r = run(fs, ps, ab)
    x = by_fac(r)[16001]
    assert x["regla"] is None and x["propuestas"][0]["confianza"] == "ALTA" and x["propuestas"][0]["diferencia"] == -1.0
    r2 = run(fs, ps, ab, [{"factura": 16001, "asignacion": "3P00000099"}])
    y = by_fac(r2)[16001]
    assert y["regla"] == "M" and y["diferencia"] == -1.0
    assert not r2["asiento_liberable"] and "diferencia" in " ".join(r2["bloqueos"])


def test_decision_con_abono_de_otro_mes():
    r = run([fac(1, 500, "A B")], [], [], [{"factura": 16001, "asignacion": "3PX", "fecha_banco": "2026-09-30", "monto_banco": 500}])
    x = by_fac(r)[16001]
    assert x["regla"] == "M" and x["fecha_banco"] == "2026-09-30" and r["asiento_liberable"]


def test_decision_conflictiva_no_se_aplica():
    fs = [fac(1, 500, "A B"), fac(2, 500, "C D")]
    r = run(fs, [], [abono("3PX", 500, D)], [{"factura": 16001, "asignacion": "3PX"}, {"factura": 16002, "asignacion": "3PX"}])
    assert r["resumen"]["conciliadas"] == 0 and r["advertencias"]


def test_resultado_no_depende_del_orden():
    rnd = random.Random(7)
    fs, ps, ab = [], [], []
    for i in range(1, 41):
        t = datetime(2026, 10, 1 + i % 20, 8 + i % 10, i, 0)
        monto = 500 + (i % 7) * 100
        fs.append(fac(i, monto, f"ALUMNO{i} APELLIDO{i}", t.date()))
        ps.append(pago(f"C{i:05d}", monto, f"Alumno{i} Apellido{i}", t))
        ab.append(abono(f"3P{i:04d}", monto, t.date(), t.hour * 3600 + t.minute * 60 - 5, luka=None if i % 3 else f"C{i:05d}"))
    base = {x["factura"]: x["asignacion"] for x in run(fs, ps, ab)["conciliadas"]}
    for _ in range(5):
        rnd.shuffle(fs); rnd.shuffle(ps); rnd.shuffle(ab)
        assert {x["factura"]: x["asignacion"] for x in run(fs, ps, ab)["conciliadas"]} == base
    assert len(base) == 40


def test_asiento_tarjeta_dos_filas_y_qr_primero():
    t = datetime(2026, 10, 7, 10, 0, 0)
    fs = [fac(1, 930, "TARJETA UNO"), fac(2, 784, "QR DOS")]
    ps = [pago("T1", 930, "x", t, metodo="TARJETA"), pago("Q2", 784, "y", t)]
    c = Conciliador(*fuentes(fs, ps, [abono("3PL", 916.98, date(2026, 10, 8), linkser=True), abono("3PQ", 784, D, luka="Q2")]), None, Parametros())
    res = c.ejecutar()
    filas = asiento_filas(res["_enlaces"], Parametros())
    assert [f["tipo"] for f in filas] == ["QR", "TARJETA", "COMISION"]
    assert filas[2]["valores"][12] == "HOLALUKA-10" and filas[2]["valores"][14] == "110201007"
    assert filas[0]["valores"][15] == "F-16002 QR DOS"
    xlsx = construir_excel(res, Parametros())
    wb = openpyxl.load_workbook(io.BytesIO(xlsx))
    assert {"RESUMEN", "ASIENTO", "CONCILIACION", "EXCEPCIONES", "DECISIONES", "CONTROLES"} <= set(wb.sheetnames)


# ---------------------------------------------------------------- lectores
def _xlsx(rows, title="Hoja1"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_lectores_detectan_y_leen():
    sint = _xlsx([["UNIVERSIDAD"], ["CAJA: SINTESISCB"], [],
                  ["Nº", "Fecha", "Nº de Factura", "Nombre o Razón Social", "Alumno/Participante", "Carrera", "NIT",
                   "Total Bruto (Bs.)", "Descuento (Bs.)", "Importe Neto (Bs.)", "Monto ($us.)"],
                  [1, datetime(2026, 10, 1), -10001, "Perez", "PEREZ ROCA ANA LUCIA", "MED", 1, 784, 0, 784, 784],
                  [2, datetime(2026, 10, 2), -10002, "ANULADO", None, None, None, 0, 0, 0, 0]])
    f = leer("sintesis.xlsx", sint)
    assert f.tipo == "SINTESIS" and f.filas == 1 and f.registros[0].factura == 10001 and f.detalle["caja"] == "SINTESISCB"

    banco = _xlsx([["fecha", "Hora", "Oficina", "Descripción", "Referencia", "Código de transacción", "ITF", "Débitos", "Créditos", "Saldo", "Adicionales"],
                   [datetime(2026, 10, 1), "10:38:20", "CBBA", "Abono", "x", "3P00000001", 0, None, 784, 1, "Nombre Originante: PERSONA PRUEBA. Dato Adicional: LUKA AAA111. 1 CUOTA"],
                   [datetime(2026, 10, 1), "10:40:00", "CBBA", "Debito", "x", "3P0", 0, 50, None, 1, ""]])
    b = leer("BANCO.xlsx", banco)
    assert b.tipo == "BANCO" and b.filas == 1 and b.registros[0].luka_code == "AAA111" and b.registros[0].hora_s == 38300

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Código", "Canal", "Estado", "Descripción", "Ref. empresa", "Monto", "Fecha de intento de pago",
                "Método de intento de pago", "Fecha de cumplimiento", "Estado de cumplimiento", "Receptor personalizado"])
    w.writerow(["AAA111", "lukaBo", "Aprobado", "1 Cuota. Colegiatura MED - Ana Lucia Perez", "ABC1234567", "784",
                "2026/10/01 10:38:28", "QR", "2026/10/01 10:38:34", "Exitoso", "C"])
    # fila completa entre comillas (formato alterno de LUKA)
    inner = 'X1X1X1,lukaBo,Aprobado,"Desc - Ana",REF0000001,500,2026/10/01 11:00:00,QR,2026/10/01 11:00:05,Exitoso,C'
    data = out.getvalue() + '"' + inner.replace('"', '""') + '"\n'
    l = leer("luka.csv", data.encode("utf-8"))
    assert l.tipo == "LUKA" and l.filas == 2 and l.registros[1].codigo == "X1X1X1" and l.registros[1].alumno == "Ana"

    res = conciliar(f, l, b)
    assert res["resumen"]["conciliadas"] == 1 and res["conciliadas"][0]["regla"] == "R1"


def test_archivo_en_casilla_equivocada():
    from app.lectores import ErrorFuente
    banco = _xlsx([["fecha", "Código de transacción", "Créditos"], [datetime(2026, 10, 1), "3P1", 10]])
    with pytest.raises(ErrorFuente):
        leer("x.xlsx", banco, "SINTESIS")


def test_diferencia_con_ajuste_libera_y_genera_linea():
    t = datetime(2026, 10, 2, 15, 16, 31)
    fs = [fac(1, 1106, "SALAZAR VEGA MARCO ANTONIO", date(2026, 10, 8))]
    ps = [pago("CCC333", 1106, "Marco Antonio Salazar Vega", t, datetime(2026, 10, 8, 8, 49))]
    ab = [abono("3P00000099", 1107, date(2026, 10, 2), luka="CCC333")]
    dec = [{"factura": 16001, "asignacion": "3P00000099", "ajuste_cuenta": "420101010"}]
    c = Conciliador(*fuentes(fs, ps, ab), dec, Parametros())
    res = c.ejecutar()
    assert res["asiento_liberable"], res["bloqueos"]
    assert res["conciliadas"][0]["ajuste"]["lado"] == "HABER"
    filas = asiento_filas(res["_enlaces"], Parametros())
    assert [f["tipo"] for f in filas] == ["QR", "AJUSTE"]
    aj = filas[1]["valores"]
    assert aj[11] == 1.0 and aj[12] == "DIF.CBIO" and aj[14] == "420101010" and "HABER" in aj[16]
    assert aj[15] == "DIFERENCIA DE CAMBIO HOLALUKA"
    # el ajuste viaja en la hoja DECISIONES y se relee
    xlsx = construir_excel(res, Parametros())
    d = leer("prev.xlsx", xlsx)
    assert d.tipo == "DECISIONES" and d.registros[0]["ajuste_cuenta"] == "420101010"
    assert d.registros[0]["asignacion"] == "3P00000099"


def test_banco_menor_ajuste_al_debe():
    r = run([fac(1, 500, "A B")], [], [abono("3PX", 498, D)], [{"factura": 16001, "asignacion": "3PX", "ajuste_cuenta": "420101010"}])
    assert r["conciliadas"][0]["ajuste"]["lado"] == "DEBE" and r["asiento_liberable"]


def test_plantilla_sap_cuadra_y_conserva_plantilla():
    import zipfile
    from app.sap import generar_plantilla, PLANTILLA
    t = datetime(2026, 10, 7, 10, 0, 0)
    fs = [fac(1, 930, "TARJETA UNO"), fac(2, 784, "QR DOS"), fac(3, 1106, "MANUAL TRES", date(2026, 10, 8))]
    ps = [pago("T1", 930, "x", t, metodo="TARJETA"), pago("Q2", 784, "y", t), pago("M3", 1106, "z", t, datetime(2026, 10, 8, 9))]
    ab = [abono("3PL", 916.98, date(2026, 10, 8), linkser=True), abono("3PQ", 784, D, luka="Q2"), abono("3PM", 1107, D, luka="M3")]
    c = Conciliador(*fuentes(fs, ps, ab), [{"factura": 16003, "asignacion": "3PM", "ajuste_cuenta": "420101010"}], Parametros())
    res = c.ejecutar()
    assert res["asiento_liberable"]
    data, resumen = generar_plantilla(res["_enlaces"], Parametros(), date(2026, 10, 31))
    assert resumen["debe"] == resumen["haber"] == pytest.approx(916.98 + 13.02 + 784 + 1107)
    ws = openpyxl.load_workbook(io.BytesIO(data)).worksheets[0]
    assert [ws[c].value for c in ("B10", "C10", "F10", "H10")] == ["BO01", "DB", "10", "BOB"]
    assert ws["E10"].value == datetime(2026, 10, 31)
    filas = [[ws.cell(r, c).value for c in (3, 4, 5, 6, 12, 18)] for r in range(16, ws.max_row + 1)]
    assert filas[0] == [110103012, "F-16002 QR DOS", 784, None, 10010101, "3PQ"]
    assert [f[0] for f in filas] == [110103012, 110103012, 110201007, 110103012, 110101001, 110101001, 420101010]
    assert filas[-1] == [420101010, "DIFERENCIA DE CAMBIO HOLALUKA", None, 1, 10010101, "DIF.CBIO"]
    a, b = zipfile.ZipFile(PLANTILLA), zipfile.ZipFile(io.BytesIO(data))
    cambiadas = {n for n in a.namelist() if a.read(n) != b.read(n)}
    assert cambiadas == {"xl/worksheets/sheet1.xml", "xl/sharedStrings.xml", "xl/styles.xml"}


def test_plantilla_sap_rechaza_descuadre():
    from app.sap import ErrorSAP, LineaSAP, validar
    with pytest.raises(ErrorSAP):
        validar([LineaSAP("110103012", "X", 100, 0, D, "A", "QR")], Parametros())
