"""API sin estado: recibe los archivos del mes, concilia en memoria y devuelve el resultado + Excel.
Nada se guarda en disco ni en base de datos."""
from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .excel import construir_excel
from .lectores import ErrorFuente, leer
from .motor import VERSION, Parametros, conciliar

MAX_MB = 25
STATIC = Path(__file__).resolve().parent.parent / "static"
ACCESS_KEY = os.environ.get("ACCESS_KEY", "").strip()

app = FastAPI(title="Conciliador HOLALUKA", version=VERSION, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def seguridad(request: Request, call_next):
    if ACCESS_KEY and request.url.path.startswith("/api/"):
        clave = request.headers.get("x-access-key", "")
        if not secrets.compare_digest(clave, ACCESS_KEY):
            return JSONResponse({"error": "Clave de acceso requerida."}, status_code=401)
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else resp.headers.get("Cache-Control", "no-cache")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


async def _leer_upload(up: UploadFile, tipo: str | None = None):
    data = await up.read()
    if len(data) > MAX_MB * 1024 * 1024:
        raise ErrorFuente(f"{up.filename}: supera {MAX_MB} MB.")
    if not data:
        raise ErrorFuente(f"{up.filename}: el archivo está vacío.")
    return leer(up.filename or "archivo", data, tipo)


@app.exception_handler(ErrorFuente)
async def error_fuente(_, exc: ErrorFuente):
    return JSONResponse({"error": str(exc)}, status_code=422)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "version": VERSION, "requiere_clave": bool(ACCESS_KEY)}


@app.post("/api/inspeccionar")
async def inspeccionar(archivo: UploadFile = File(...)):
    f = await _leer_upload(archivo)
    return f.resumen()


@app.post("/api/conciliar")
async def api_conciliar(
    sintesis: UploadFile = File(...),
    banco: UploadFile = File(...),
    luka: UploadFile = File(...),
    decisiones_archivo: UploadFile | None = File(None),
    decisiones: str = Form("[]"),
    parametros: str = Form("{}"),
):
    s = await _leer_upload(sintesis, "SINTESIS")
    b = await _leer_upload(banco, "BANCO")
    l = await _leer_upload(luka, "LUKA")
    decs = []
    if decisiones_archivo is not None and decisiones_archivo.filename:
        decs += (await _leer_upload(decisiones_archivo, "DECISIONES")).registros
    try:
        decs_ui = json.loads(decisiones or "[]")
        p = Parametros.desde_dict(json.loads(parametros or "{}"))
    except (ValueError, TypeError) as exc:
        raise ErrorFuente(f"Parámetros o decisiones inválidos: {exc}") from exc
    # Las decisiones tomadas en pantalla prevalecen sobre las del archivo para la misma factura.
    fac_ui = {int(d["factura"]) for d in decs_ui}
    decs = [d for d in decs if d["factura"] not in fac_ui] + [{**d, "origen": "PANTALLA"} for d in decs_ui]

    res = conciliar(s, l, b, decs, p)
    xlsx = construir_excel(res, p)
    res.pop("_enlaces", None)
    periodo = res["periodo"]["desde"][:7]
    res["excel_nombre"] = f"Conciliacion_HOLALUKA_{periodo}.xlsx"
    res["excel_b64"] = base64.b64encode(xlsx).decode()
    res["decisiones_aplicadas"] = [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()} for d in decs]
    return JSONResponse(json.loads(json.dumps(res, default=str)))
