"""Utilidades puras: normalizacion de texto, montos en centavos, fechas y horas."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher

EXCEL_EPOCH = datetime(1899, 12, 30)


def norm(s) -> str:
    """Mayusculas, sin tildes, sin puntuacion, espacios colapsados."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_header(s) -> str:
    return norm(s).replace(" ", "")


# ----------------------------------------------------------------- montos
def to_decimal(v) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        try:
            return Decimal(str(v))
        except InvalidOperation:
            return None
    s = str(v).strip().replace("Bs.", "").replace("Bs", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        dec = s.split(",")[-1]
        s = s.replace(",", ".") if len(dec) in (1, 2) and s.count(",") == 1 else s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def to_cents(v) -> int | None:
    d = to_decimal(v)
    if d is None:
        return None
    return int((d * 100).quantize(Decimal("1"), ROUND_HALF_UP))


def round_cents(cents_value: Decimal) -> int:
    return int(cents_value.quantize(Decimal("1"), ROUND_HALF_UP))


def bs(cents: int | None) -> float | None:
    return None if cents is None else cents / 100


# ----------------------------------------------------------------- fechas
_DATE_FORMATS = (
    "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S",
    "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M", "%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y",
)


def to_datetime(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 < float(v) < 80000:
            return EXCEL_EPOCH + timedelta(days=float(v))
        return None
    s = str(v).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    m = re.match(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    return None


def to_date(v) -> date | None:
    dt = to_datetime(v)
    return dt.date() if dt else None


def to_seconds(v) -> int | None:
    """Segundos del dia desde time, datetime, fraccion Excel o texto HH:MM:SS."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.hour * 3600 + v.minute * 60 + v.second
    if isinstance(v, time):
        return v.hour * 3600 + v.minute * 60 + v.second
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        frac = float(v) % 1
        return int(round(frac * 86400)) % 86400
    m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", str(v))
    if m:
        return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3] or 0)
    return None


# ----------------------------------------------------------------- nombres
STOP = {"DE", "DEL", "LOS", "LAS", "LA", "Y", "SRL", "CUOTA", "COLEGIATURA", "HOLALUKA", "LUKA",
        "CUENTA", "ORIGEN", "NOMBRE", "ORIGINANTE", "BANCO", "DATO", "ADICIONAL", "ABONO"}


def name_tokens(s) -> set[str]:
    return {t for t in norm(s).split() if len(t) >= 3 and not t.isdigit() and t not in STOP}


def name_similarity(a, b) -> float:
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def strong_name_evidence(student, other) -> bool:
    """Dos tokens exactos (>=4 letras) o uno exacto + uno largo con variacion tipografica."""
    ta = {t for t in name_tokens(student) if len(t) >= 4}
    tb = {t for t in name_tokens(other) if len(t) >= 4}
    exact = ta & tb
    if len(exact) >= 2:
        return True
    if len(exact) == 1:
        for x in ta - exact:
            if len(x) < 7:
                continue
            for y in tb - exact:
                if len(y) >= 7 and SequenceMatcher(None, x, y).ratio() >= 0.85:
                    return True
    return False
