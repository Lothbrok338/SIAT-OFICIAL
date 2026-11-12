"""Regresion con los archivos reales de octubre 2026.
Los archivos van en datos/ (excluido de git mientras el repo sea publico). Si no estan, la prueba se omite."""
from pathlib import Path

import pytest

from app.lectores import leer
from app.motor import conciliar

DATOS = Path(__file__).resolve().parent.parent / "datos" / "2026-10"
ARCHIVOS = {"SINTESIS": "LUKITA.xlsx", "BANCO": "BANCOS_OCTUBRE.xlsx", "LUKA": "luka-pagos-2026-10-01-2026-10-31.csv"}

pytestmark = pytest.mark.skipif(not all((DATOS / f).exists() for f in ARCHIVOS.values()),
                                reason="datos reales no disponibles en datos/2026-10")


def _fuente(tipo):
    p = DATOS / ARCHIVOS[tipo]
    return leer(p.name, p.read_bytes(), tipo)


def test_octubre_2026():
    r = conciliar(_fuente("SINTESIS"), _fuente("LUKA"), _fuente("BANCO"))
    s = r["resumen"]
    assert r["receptor"] == "C"
    assert s["facturas"] == 217 and s["conciliadas"] == 216 and s["pendientes"] == 1
    assert s["total_neto"] == pytest.approx(487566.66)
    assert s["comision_tarjetas"] == pytest.approx(137.85)
    assert s["por_regla"] == {"R1": 186, "R2": 0, "R3": 26, "R4": 4, "R5": 0, "M": 0}
    assert all(c["ok"] for c in r["controles"][:4])
    exc = r["excepciones"][0]
    assert exc["factura"] == 16530 and exc["propuestas"][0]["asignacion"] == "3P13489723"
    assert exc["propuestas"][0]["diferencia"] == pytest.approx(-1.0)
