import calendar
import re
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MONTHS = ("", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def month_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValueError("El mes no es válido.")
    try:
        parsed = date.fromisoformat(value + "-01")
    except ValueError:
        raise ValueError("El mes no es válido.") from None
    if not 2000 <= parsed.year <= 2100:
        raise ValueError("El año debe estar entre 2000 y 2100.")
    return value


def day_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("La fecha no es válida.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("La fecha no es válida.") from None
    month_value(value[:7])
    return value


def decimal_value(value):
    try:
        result = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError("Introduce un número válido.") from None
    if not result.is_finite():
        raise ValueError("Introduce un número válido.")
    return result


def hours_to_minutes(value):
    hours = decimal_value(value)
    if hours < Decimal("0.5") or hours > 24 or hours % Decimal("0.5"):
        raise ValueError("Las horas deben ir de 0,5 a 24, en intervalos de media hora.")
    return int(hours * 60)


def rate_to_cents(value):
    rate = decimal_value(value)
    if rate < 0 or rate > 10000 or rate * 100 != (rate * 100).to_integral_value():
        raise ValueError("La tarifa debe estar entre 0 y 10.000 €, con un máximo de dos decimales.")
    return int(rate * 100)


def earnings(minutes, rate_cents):
    return int((Decimal(minutes) * rate_cents / 60).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def hours_text(minutes):
    return str(Decimal(minutes) / 60).rstrip("0").rstrip(".") if minutes % 60 else str(minutes // 60)


def money_text(cents):
    return f"{cents / 100:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".") + " €"


def month_label(value):
    year, month = map(int, value.split("-"))
    return f"{MONTHS[month]} de {year}"


def day_label(value):
    d = date.fromisoformat(value)
    return f"{WEEKDAYS[d.weekday()]}, {d.day} de {MONTHS[d.month]} de {d.year}"


def adjacent_month(value, delta):
    year, month = map(int, value.split("-"))
    total = year * 12 + month - 1 + delta
    result = f"{total // 12:04d}-{total % 12 + 1:02d}"
    return result if "2000-01" <= result <= "2100-12" else None


def calendar_weeks(value):
    year, month = map(int, value.split("-"))
    return calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
