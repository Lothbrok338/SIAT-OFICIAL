"""
MOTOR DE CONCILIACION HOLALUKA v3  —  FACTURA -> PAGO LUKA -> ABONO BANCARIO

Principios
  1. Cadena de evidencia: la factura se enlaza con su pago LUKA y el pago LUKA con el abono.
     Nunca se cruza factura contra banco "a ciegas".
  2. Unicidad bilateral: un enlace se acepta solo si es el unico candidato para ambos lados.
     El resultado no depende del orden de las filas.
  3. Montos en centavos enteros: sin tolerancias ni redondeos flotantes.
  4. QR solo contra abonos HOLALUKA; tarjetas solo contra liquidaciones LINKSER.
  5. Lo dudoso no se adivina: queda como excepcion con propuestas y evidencia.
  6. Decisiones manuales se aplican primero y nunca se reescriben.
"""
from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .lectores import Abono, Factura, Fuente, PagoLuka
from .util import bs, name_similarity, norm, round_cents, strong_name_evidence

VERSION = "3.0.0"

REGLAS = {
    "R1": "Código LUKA en el abono",
    "R2": "Código estudiantil en el abono",
    "R3": "Monto exacto + hora del intento LUKA",
    "R4": "Liquidación LINKSER (tarjeta)",
    "R5": "Monto + fecha + nombre del depositante",
    "M": "Decisión manual",
}


@dataclass
class Parametros:
    comision_tarjeta: Decimal = Decimal("0.014")
    max_dias_linkser: int = 4
    ventana_segundos: int = 120
    cuenta_qr: str = "110103012"
    cuenta_tarjeta: str = "110103012"
    cuenta_comision: str = "110201007"
    cuenta_diferencias: str = "420101010"   # Varios otros: ajuste de diferencias confirmadas
    prefijo_glosa: str = "F-"
    max_glosa: int = 50
    receptor: str = ""                 # vacio = deteccion automatica
    permitir_asiento_con_pendientes: bool = False

    @classmethod
    def desde_dict(cls, d: dict | None) -> "Parametros":
        p = cls()
        if not d:
            return p
        if d.get("comision_tarjeta") not in (None, ""):
            v = Decimal(str(d["comision_tarjeta"]).replace(",", "."))
            p.comision_tarjeta = v / 100 if v >= 1 else v
        for k in ("max_dias_linkser", "ventana_segundos", "max_glosa"):
            if d.get(k) not in (None, ""):
                setattr(p, k, int(d[k]))
        for k in ("cuenta_qr", "cuenta_tarjeta", "cuenta_comision", "cuenta_diferencias", "prefijo_glosa", "receptor"):
            if d.get(k) is not None:
                setattr(p, k, str(d[k]).strip())
        p.receptor = p.receptor.upper()
        p.permitir_asiento_con_pendientes = bool(d.get("permitir_asiento_con_pendientes", False))
        return p

    def como_dict(self) -> dict:
        return {
            "comision_tarjeta": float(self.comision_tarjeta), "max_dias_linkser": self.max_dias_linkser,
            "ventana_segundos": self.ventana_segundos, "cuenta_qr": self.cuenta_qr,
            "cuenta_tarjeta": self.cuenta_tarjeta, "cuenta_comision": self.cuenta_comision,
            "cuenta_diferencias": self.cuenta_diferencias,
            "prefijo_glosa": self.prefijo_glosa, "max_glosa": self.max_glosa, "receptor": self.receptor,
            "permitir_asiento_con_pendientes": self.permitir_asiento_con_pendientes,
        }


@dataclass
class Enlace:
    factura: Factura
    pago: PagoLuka | None = None
    abono: Abono | None = None
    regla: str | None = None
    metodo: str = ""
    monto_banco_c: int | None = None
    fecha_banco: date | None = None
    comision_c: int = 0
    diferencia_c: int = 0
    lote: str = ""
    evidencia: str = ""
    motivo_pago: str = ""          # por que no se encontro pago LUKA
    propuestas: list = field(default_factory=list)
    nota_manual: str = ""
    ajuste: dict | None = None     # {cuenta, asignacion, texto} cuando el usuario confirma el ajuste de la diferencia

    @property
    def conciliada(self) -> bool:
        return self.regla is not None


# ----------------------------------------------------------------- emparejamiento con unicidad bilateral
def emparejar(cands: dict) -> tuple[dict, dict]:
    """cands: izquierda -> set(derecha). Devuelve (enlaces, ambiguos restantes)."""
    cands = {k: set(v) for k, v in cands.items() if v}
    enlaces: dict = {}
    cambio = True
    while cambio and cands:
        cambio = False
        rev = defaultdict(set)
        for k, vs in cands.items():
            for v in vs:
                rev[v].add(k)
        for k in list(cands):
            vs = cands[k]
            if len(vs) == 1:
                v = next(iter(vs))
                if len(rev[v]) == 1:
                    enlaces[k] = v
                    del cands[k]
                    cambio = True
        usados = set(enlaces.values())
        for k in list(cands):
            cands[k] -= usados
            if not cands[k]:
                del cands[k]
    return enlaces, cands


def filtrar(cands: dict, pred) -> dict:
    """Reduce cada conjunto a los candidatos que cumplen pred, solo si queda alguno."""
    out = {}
    for k, vs in cands.items():
        sub = {v for v in vs if pred(k, v)}
        out[k] = sub or vs
    return out


def mejor_por_puntaje(cands: dict, score) -> dict:
    """Deja, por cada izquierda, solo los candidatos con el mejor puntaje (> 0)."""
    out = {}
    for k, vs in cands.items():
        pts = {v: score(k, v) for v in vs}
        mx = max(pts.values())
        out[k] = {v for v, s in pts.items() if s == mx} if mx > 0 else vs
    return out


# ----------------------------------------------------------------- motor
class Conciliador:
    def __init__(self, sint: Fuente, luka: Fuente, banco: Fuente, decisiones: list[dict] | None, p: Parametros):
        self.p = p
        self.facturas: list[Factura] = sorted(sint.registros, key=lambda f: f.fila)
        self.pagos: list[PagoLuka] = [x for x in luka.registros if x.exitoso and x.f_cump]
        self.pagos_todos = {x.codigo: x for x in luka.registros}
        self.abonos: list[Abono] = banco.registros
        self.abono_por_asig = {a.asig: a for a in self.abonos}
        self.decisiones = decisiones or []
        self.fuentes = (sint, luka, banco)
        self.E: dict[int, Enlace] = {f.factura: Enlace(f) for f in self.facturas}
        self.abonos_usados: set[str] = set()
        self.pagos_usados: set[str] = set()
        self.advertencias: list[str] = []
        self.periodo = (min(f.fecha for f in self.facturas), max(f.fecha for f in self.facturas))
        self.receptor = ""

    # ---------------------------------------------------- utilidades
    def _neto_tarjeta(self, neto_c: int) -> int:
        return round_cents(Decimal(neto_c) * (1 - self.p.comision_tarjeta))

    def _asignar_banco(self, e: Enlace, a: Abono, regla: str, evidencia: str):
        e.abono, e.regla, e.evidencia = a, regla, evidencia
        e.monto_banco_c, e.fecha_banco = a.monto_c, a.fecha
        e.metodo = e.metodo or "QR"
        self.abonos_usados.add(a.asig)

    def _libres(self, pred):
        return [a for a in self.abonos if a.asig not in self.abonos_usados and pred(a)]

    # ---------------------------------------------------- 0. receptor de la sede
    def detectar_receptor(self):
        if self.p.receptor:
            self.receptor = self.p.receptor
            return
        llave = defaultdict(list)
        for x in self.pagos:
            llave[(x.f_cump.date(), x.monto_c)].append(x)
        conteo = defaultdict(int)
        for f in self.facturas:
            for x in llave.get((f.fecha, f.neto_c), []):
                conteo[x.receptor] += 1
        if conteo:
            rec, n = max(conteo.items(), key=lambda kv: kv[1])
            total = sum(conteo.values())
            if rec and n / total >= 0.8:
                self.receptor = rec
        if not self.receptor:
            self.advertencias.append("No se pudo determinar el receptor de la sede en LUKA: se compararon pagos de todas las sedes.")

    # ---------------------------------------------------- 1. decisiones manuales
    def aplicar_decisiones(self):
        por_asig = defaultdict(set)
        for d in self.decisiones:
            por_asig[str(d["asignacion"]).strip().upper()].add(int(d["factura"]))
        conflictivas = {k for k, v in por_asig.items() if len(v) > 1}
        for k in conflictivas:
            self.advertencias.append(f"La asignación {k} está decidida para varias facturas ({', '.join(map(str, sorted(por_asig[k])))}). No se aplicó; revisión obligatoria.")
        vistas = set()
        for d in self.decisiones:
            fac, asig = int(d["factura"]), str(d["asignacion"]).strip()
            if asig.upper() in conflictivas or fac in vistas:
                continue
            vistas.add(fac)
            e = self.E.get(fac)
            if e is None:
                self.advertencias.append(f"Decisión para la factura {fac}: no está en la Síntesis cargada (se ignoró).")
                continue
            a = self.abono_por_asig.get(asig)
            if a and a.asig in self.abonos_usados:
                self.advertencias.append(f"Decisión factura {fac}: la asignación {asig} ya fue usada (se ignoró).")
                continue
            if a:
                monto_c, fecha = a.monto_c, a.fecha
                self.abonos_usados.add(a.asig)
                origen = "abono presente en el extracto"
            else:
                monto_c = round(float(d.get("monto_banco") or 0) * 100)
                fecha = d.get("fecha_banco")
                if isinstance(fecha, str):
                    from .util import to_date
                    fecha = to_date(fecha)
                if monto_c <= 0 or not fecha:
                    self.advertencias.append(f"Decisión factura {fac}: la asignación {asig} no está en el extracto; indica fecha y monto del banco.")
                    continue
                origen = "abono verificado fuera del extracto"
            e.abono, e.regla, e.metodo = a, "M", "MANUAL"
            e.asig_manual = asig
            e.monto_banco_c, e.fecha_banco = monto_c, fecha
            e.diferencia_c = e.factura.neto_c - monto_c
            e.nota_manual = str(d.get("nota") or "")
            if e.diferencia_c and str(d.get("ajuste_cuenta") or "").strip():
                e.ajuste = {
                    "cuenta": str(d["ajuste_cuenta"]).strip(),
                    "asignacion": str(d.get("ajuste_asignacion") or asig).strip(),
                    "texto": str(d.get("ajuste_texto") or f"AJ F-{fac} DIF BANCO").strip().upper(),
                    "lado": "HABER" if e.diferencia_c < 0 else "DEBE",
                }
            e.evidencia = f"Decisión manual ({origen})" + (f" · {e.nota_manual}" if e.nota_manual else "")

    # ---------------------------------------------------- 2. factura <-> pago LUKA
    def enlazar_luka(self):
        pagos = [x for x in self.pagos if not self.receptor or x.receptor in (self.receptor, "")]
        por_cod = {x.codigo: x for x in pagos}
        llave = defaultdict(set)
        for x in pagos:
            llave[(x.f_cump.date(), x.monto_c)].add(x.codigo)
        cands = {f.factura: set(llave.get((f.fecha, f.neto_c), set())) for f in self.facturas}
        enl, amb = emparejar(cands)
        if amb:  # desempate por nombre del estudiante
            fx = {f.factura: f for f in self.facturas}
            amb = mejor_por_puntaje(amb, lambda k, v: name_similarity(fx[k].alumno, por_cod[v].alumno))
            e2, amb = emparejar({k: v - set(enl.values()) for k, v in amb.items()})
            enl.update(e2)
        for fac, cod in enl.items():
            e = self.E[fac]
            e.pago = por_cod[cod]
            e.metodo = e.metodo or e.pago.metodo
            self.pagos_usados.add(cod)
        for fac, e in self.E.items():
            if e.pago is None:
                if fac in amb:
                    e.motivo_pago = f"Hay {len(amb[fac])} pagos LUKA posibles con la misma fecha y monto"
                else:
                    e.motivo_pago = "No hay pago LUKA con la misma fecha de cumplimiento y monto"

    # ---------------------------------------------------- 3. pago LUKA <-> abono
    def pendientes(self, metodo=None):
        return [e for e in self.E.values() if not e.conciliada and e.pago and (metodo is None or e.pago.metodo == metodo)]

    def regla_r1(self):
        por_cod = defaultdict(list)
        for a in self.abonos:
            if a.luka_code:
                por_cod[a.luka_code].append(a)
        for e in self.pendientes():
            lista = [a for a in por_cod.get(e.pago.codigo, []) if a.asig not in self.abonos_usados]
            if len(lista) == 1 and lista[0].monto_c == e.factura.neto_c:
                self._asignar_banco(e, lista[0], "R1", f"El abono trae el código LUKA {e.pago.codigo}")

    def regla_r2(self):
        cands = {}
        for e in self.pendientes():
            if not e.pago.ref:
                continue
            ini = (e.pago.f_int or e.pago.f_cump).date() - timedelta(days=1)
            fin = e.pago.f_cump.date() + timedelta(days=3)
            cands[e.factura.factura] = {a.asig for a in self._libres(
                lambda a: a.es_luka and a.cod_est == e.pago.ref and a.monto_c == e.factura.neto_c and ini <= a.fecha <= fin)}
        enl, _ = emparejar(cands)
        for fac, asig in enl.items():
            e = self.E[fac]
            self._asignar_banco(e, self.abono_por_asig[asig], "R2", f"El abono trae el código estudiantil {e.pago.ref}")

    def regla_r3(self):
        w = self.p.ventana_segundos
        cands, deltas = {}, {}
        for e in self.pendientes("QR"):
            t = e.pago.f_int
            if not t:
                continue
            ts = t.hour * 3600 + t.minute * 60 + t.second
            libres = self._libres(lambda a: a.es_luka and a.luka_code is None and a.monto_c == e.factura.neto_c
                                  and a.fecha == t.date() and a.hora_s is not None and abs(a.hora_s - ts) <= w)
            cands[e.factura.factura] = {a.asig for a in libres}
            for a in libres:
                deltas[(e.factura.factura, a.asig)] = a.hora_s - ts
        enl, _ = emparejar(cands)
        for fac, asig in enl.items():
            d = deltas[(fac, asig)]
            self._asignar_banco(self.E[fac], self.abono_por_asig[asig], "R3",
                                f"Monto exacto; abono {abs(d)} s {'antes' if d <= 0 else 'después'} del intento LUKA")

    def regla_r5(self):
        cands = {}
        for e in self.pendientes("QR"):
            fechas = {d for d in ((e.pago.f_int.date() if e.pago.f_int else None), e.pago.f_cump.date()) if d}
            cands[e.factura.factura] = {a.asig for a in self._libres(
                lambda a: a.es_luka and a.luka_code is None and a.monto_c == e.factura.neto_c and a.fecha in fechas
                and strong_name_evidence(e.factura.alumno + " " + e.pago.alumno, a.originante + " " + a.texto))}
        enl, _ = emparejar(cands)
        for fac, asig in enl.items():
            self._asignar_banco(self.E[fac], self.abono_por_asig[asig], "R5", "Monto y fecha exactos; el nombre del depositante coincide con el estudiante")

    def regla_r4(self):
        tarjetas = self.pendientes("TARJETA")
        if not tarjetas:
            return
        neto_b = {e.factura.factura: self._neto_tarjeta(e.factura.neto_c) for e in tarjetas}
        libres = {e.factura.factura: e for e in tarjetas}
        for a in sorted(self._libres(lambda a: a.es_linkser), key=lambda a: (a.fecha, a.hora_s or 0, a.asig)):
            elig = [e for e in libres.values() if 0 <= (a.fecha - e.pago.f_cump.date()).days <= self.p.max_dias_linkser]
            if not elig or len(elig) > 22:
                continue
            sol = self._subconjunto_exacto(elig, neto_b, a)
            if not sol:
                continue
            lote = a.asig if len(sol) > 1 else ""
            for e in sol:
                nb = neto_b[e.factura.factura]
                e.abono, e.regla, e.metodo = a, "R4", "TARJETA"
                e.monto_banco_c, e.fecha_banco = nb, a.fecha
                e.comision_c = e.factura.neto_c - nb
                e.lote = lote
                e.evidencia = (f"Liquidación LINKSER de Bs {a.monto_c/100:,.2f}: neto {nb/100:,.2f} + comisión "
                               f"{e.comision_c/100:,.2f} ({float(self.p.comision_tarjeta)*100:.2f} %)"
                               + (f" · lote de {len(sol)} tarjetas" if lote else ""))
                del libres[e.factura.factura]
            self.abonos_usados.add(a.asig)

    def _subconjunto_exacto(self, elig, neto_b, a):
        """Menor cantidad de tarjetas cuya suma neta = abono; desempata por menor demora. Debe ser unico."""
        for k in range(1, min(len(elig), 8) + 1):
            mejores, mejor_lag = [], None
            for comb in itertools.combinations(elig, k):
                if sum(neto_b[e.factura.factura] for e in comb) != a.monto_c:
                    continue
                lag = sum((a.fecha - e.pago.f_cump.date()).days for e in comb)
                if mejor_lag is None or lag < mejor_lag:
                    mejores, mejor_lag = [comb], lag
                elif lag == mejor_lag:
                    mejores.append(comb)
            if mejores:
                return list(mejores[0]) if len(mejores) == 1 else None
        return None

    # ---------------------------------------------------- 4. propuestas para excepciones
    def proponer(self):
        for e in self.E.values():
            if e.conciliada:
                continue
            f, x, props = e.factura, e.pago, []
            if x:
                for a in self.abonos:
                    if a.luka_code == x.codigo and a.asig not in self.abonos_usados:
                        props.append(self._prop(a, f, "ALTA", f"El abono trae el código LUKA {x.codigo}, pero el monto difiere"))
            ref = (x.f_int.date() if x and x.f_int else f.fecha)
            pool = (lambda a: a.es_linkser) if (x and x.metodo == "TARJETA") else (lambda a: a.es_luka or not a.es_linkser)
            vistos = {p["asignacion"] for p in props}
            for a in self._libres(pool):
                if a.asig in vistos or abs((a.fecha - ref).days) > 5:
                    continue
                if x and x.metodo == "TARJETA":
                    if a.monto_c >= self._neto_tarjeta(f.neto_c):
                        props.append(self._prop(a, f, "BAJA", "Liquidación LINKSER libre en la ventana de días (revisa el detalle de ATC/LINKSER)"))
                    continue
                if a.monto_c != f.neto_c:
                    continue
                fuerte = strong_name_evidence(f.alumno, a.originante + " " + a.texto)
                conf = "MEDIA" if (fuerte and a.es_luka) else "BAJA"
                motivo = "Mismo monto" + (", abono HOLALUKA" if a.es_luka else ", abono no HOLALUKA") + (", el nombre coincide" if fuerte else "")
                props.append(self._prop(a, f, conf, motivo))
            orden = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}
            e.propuestas = sorted(props, key=lambda p: (orden[p["confianza"]], abs(p["diferencia"]), p["fecha"]))[:6]

    @staticmethod
    def _prop(a: Abono, f: Factura, conf: str, motivo: str) -> dict:
        return {"asignacion": a.asig, "fecha": a.fecha.isoformat(), "monto": a.monto_c / 100,
                "diferencia": (f.neto_c - a.monto_c) / 100, "depositante": a.originante or a.texto[:60],
                "codigo_luka": a.luka_code, "confianza": conf, "motivo": motivo}

    # ---------------------------------------------------- 5. lado banco / LUKA sin factura
    def huerfanos(self):
        d0, d1 = self.periodo
        enl_por_cod = {e.pago.codigo: e for e in self.E.values() if e.pago}
        abonos = []
        for a in self.abonos:
            if a.asig in self.abonos_usados or not (a.es_luka or a.es_linkser):
                continue
            if a.es_linkser:
                clas = "Liquidación LINKSER sin tarjetas asociadas"
            elif a.luka_code:
                x = self.pagos_todos.get(a.luka_code)
                if x and x.codigo in enl_por_cod:
                    clas = f"Pago de la factura {enl_por_cod[x.codigo].factura.factura} con monto distinto (ver excepciones)"
                elif x and self.receptor and x.receptor and x.receptor != self.receptor:
                    clas = f"Pago LUKA de otra sede (receptor {x.receptor})"
                elif x:
                    clas = "Pago LUKA cumplido SIN FACTURA en la Síntesis"
                elif a.fecha > d1:
                    clas = "Pago del período siguiente (código no está en el CSV del mes)"
                elif a.fecha < d0:
                    clas = "Pago del período anterior (código no está en el CSV del mes)"
                else:
                    clas = "Código LUKA que no figura en el CSV del mes"
            else:
                clas = "Abono HOLALUKA sin código ni factura" if d0 <= a.fecha <= d1 else "Abono HOLALUKA fuera del período"
            abonos.append({"asignacion": a.asig, "fecha": a.fecha.isoformat(), "monto": a.monto_c / 100,
                           "codigo_luka": a.luka_code, "depositante": a.originante or a.texto[:60],
                           "clasificacion": clas, "en_periodo": d0 <= a.fecha <= d1})
        banco_por_cod = {a.luka_code: a for a in self.abonos if a.luka_code}
        luka_sin = []
        for x in self.pagos:
            if x.codigo in self.pagos_usados or (self.receptor and x.receptor not in (self.receptor, "")):
                continue
            if not (d0 <= x.f_cump.date() <= d1):
                continue
            a = banco_por_cod.get(x.codigo)
            if self.receptor and x.receptor == "" and a is None:
                continue  # pago sin sede declarada y sin abono en este banco: no es de esta sede
            luka_sin.append({"codigo": x.codigo, "alumno": x.alumno, "codigo_estudiante": x.ref, "monto": x.monto_c / 100,
                             "metodo": x.metodo, "fecha_cumplimiento": x.f_cump.isoformat(sep=" "),
                             "receptor": x.receptor, "asignacion_banco": a.asig if a else None})
        return abonos, luka_sin

    # ---------------------------------------------------- ejecutar
    def ejecutar(self) -> dict:
        self.detectar_receptor()
        self.aplicar_decisiones()
        self.enlazar_luka()
        for regla in (self.regla_r1, self.regla_r2, self.regla_r3, self.regla_r4, self.regla_r5):
            regla()
        self.proponer()
        abonos_sin, luka_sin = self.huerfanos()
        return self._resultado(abonos_sin, luka_sin)

    # ---------------------------------------------------- controles y salida
    def _resultado(self, abonos_sin, luka_sin) -> dict:
        E = list(self.E.values())
        conc = [e for e in E if e.conciliada]
        pend = [e for e in E if not e.conciliada]
        tot = sum(e.factura.neto_c for e in E)
        tot_conc = sum(e.factura.neto_c for e in conc)
        comision = sum(e.comision_c for e in conc)
        con_dif = [e for e in conc if e.diferencia_c and not e.ajuste]
        ajustadas = [e for e in conc if e.diferencia_c and e.ajuste]
        respaldo = sum((e.monto_banco_c or 0) + e.comision_c + e.diferencia_c for e in conc)

        usos = defaultdict(list)
        for e in conc:
            asig = e.abono.asig if e.abono else getattr(e, "asig_manual", "")
            usos[asig.upper()].append(e)
        dup = [k for k, v in usos.items() if len(v) > 1 and not all(x.regla == "R4" and x.lote for x in v)]
        lotes_mal = []
        for k, v in usos.items():
            if len(v) > 1 and all(x.regla == "R4" for x in v):
                if sum(x.monto_banco_c for x in v) != v[0].abono.monto_c:
                    lotes_mal.append(k)
        tarjeta_mal = [e.factura.factura for e in conc if e.regla == "R4" and e.monto_banco_c + e.comision_c != e.factura.neto_c]

        sint, luka, banco = self.fuentes
        d0, d1 = self.periodo
        if luka.desde and luka.hasta and (luka.desde > d0 or luka.hasta < d1):
            self.advertencias.append(f"El CSV de LUKA cubre {luka.desde:%d/%m/%Y}–{luka.hasta:%d/%m/%Y} y la Síntesis {d0:%d/%m/%Y}–{d1:%d/%m/%Y}: descarga LUKA del mes completo.")
        if banco.hasta and banco.hasta < d1 + timedelta(days=2):
            self.advertencias.append(f"El extracto termina el {banco.hasta:%d/%m/%Y}. Incluye los primeros días del mes siguiente: las liquidaciones LINKSER y los pagos de fin de mes se acreditan después.")
        if banco.desde and banco.desde > d0 - timedelta(days=0):
            if banco.desde > d0:
                self.advertencias.append(f"El extracto empieza el {banco.desde:%d/%m/%Y}, después del inicio de la Síntesis ({d0:%d/%m/%Y}).")
        meses = {(d0.year, d0.month), (d1.year, d1.month)}
        if len(meses) > 1:
            self.advertencias.append("La Síntesis contiene facturas de más de un mes.")

        controles = [
            {"control": "Total conciliado = respaldo bancario + comisiones + diferencias", "valor": (tot_conc - respaldo) / 100, "ok": tot_conc == respaldo},
            {"control": "Asignaciones bancarias usadas más de una vez (fuera de lotes LINKSER)", "valor": len(dup), "ok": not dup, "detalle": ", ".join(dup)},
            {"control": "Lotes LINKSER cuya suma neta no iguala el abono", "valor": len(lotes_mal), "ok": not lotes_mal, "detalle": ", ".join(lotes_mal)},
            {"control": "Tarjetas donde neto + comisión ≠ importe neto", "valor": len(tarjeta_mal), "ok": not tarjeta_mal},
            {"control": "Facturas pendientes", "valor": len(pend), "ok": not pend},
            {"control": "Diferencias de monto sin ajuste contable", "valor": len(con_dif), "ok": not con_dif,
             "detalle": "; ".join(f"F-{e.factura.factura}: Bs {e.diferencia_c/100:,.2f}" for e in con_dif)},
            {"control": "Diferencias ajustadas (revisar cuenta y asignación)", "valor": len(ajustadas), "ok": True,
             "detalle": "; ".join(f"F-{e.factura.factura}: Bs {abs(e.diferencia_c)/100:,.2f} al {e.ajuste['lado']} de {e.ajuste['cuenta']}" for e in ajustadas)},
        ]
        bloqueos = []
        if pend and not self.p.permitir_asiento_con_pendientes:
            bloqueos.append(f"{len(pend)} factura(s) pendiente(s)")
        if con_dif:
            bloqueos.append(f"{len(con_dif)} diferencia(s) sin ajuste contable")
        if not all(c["ok"] for c in controles[:4]):
            bloqueos.append("controles de integridad con error")

        por_regla = {k: sum(1 for e in conc if e.regla == k) for k in REGLAS}
        return {
            "version": VERSION,
            "periodo": {"desde": d0.isoformat(), "hasta": d1.isoformat()},
            "receptor": self.receptor,
            "fuentes": [f.resumen() for f in self.fuentes],
            "parametros": self.p.como_dict(),
            "resumen": {
                "facturas": len(E), "conciliadas": len(conc), "pendientes": len(pend),
                "total_neto": tot / 100, "total_conciliado": tot_conc / 100, "total_pendiente": (tot - tot_conc) / 100,
                "comision_tarjetas": comision / 100, "por_regla": por_regla,
                "porcentaje": round(100 * len(conc) / len(E), 1) if E else 0,
                "abonos_sin_factura_periodo": sum(1 for a in abonos_sin if a["en_periodo"]),
                "luka_sin_factura": len(luka_sin),
            },
            "asiento_liberable": not bloqueos,
            "bloqueos": bloqueos,
            "controles": controles,
            "advertencias": self.advertencias,
            "reglas": REGLAS,
            "conciliadas": [self._fila(e) for e in conc],
            "excepciones": [self._fila(e) for e in pend],
            "abonos_sin_factura": abonos_sin,
            "luka_sin_factura": luka_sin,
            "_enlaces": E,
        }

    def _fila(self, e: Enlace) -> dict:
        f, x = e.factura, e.pago
        return {
            "factura": f.factura, "nro": f.nro, "fecha": f.fecha.isoformat(), "alumno": f.alumno, "carrera": f.carrera,
            "neto": f.neto_c / 100, "metodo": e.metodo or (x.metodo if x else ""),
            "codigo_luka": x.codigo if x else None, "codigo_estudiante": x.ref if x else None,
            "alumno_luka": x.alumno if x else None,
            "intento_luka": x.f_int.isoformat(sep=" ") if x and x.f_int else None,
            "regla": e.regla, "regla_nombre": REGLAS.get(e.regla, ""),
            "asignacion": (e.abono.asig if e.abono else getattr(e, "asig_manual", None)),
            "fecha_banco": e.fecha_banco.isoformat() if e.fecha_banco else None,
            "monto_banco": bs(e.monto_banco_c), "comision": e.comision_c / 100, "diferencia": e.diferencia_c / 100,
            "lote": e.lote, "evidencia": e.evidencia, "ajuste": e.ajuste,
            "motivo": (e.motivo_pago or (f"Pago LUKA {x.codigo} sin abono bancario identificable" if x else "")) if not e.conciliada else "",
            "propuestas": e.propuestas,
        }


def conciliar(sint: Fuente, luka: Fuente, banco: Fuente, decisiones=None, parametros: Parametros | None = None) -> dict:
    return Conciliador(sint, luka, banco, decisiones, parametros or Parametros()).ejecutar()
