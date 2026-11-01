from .domain import frequency_value, month_value, day_value, week_value


def validate_backup(payload):
    def integer(value, low, high, step=1):
        if type(value) is not int or not low <= value <= high or value % step:
            raise ValueError("La copia contiene una cantidad no válida.")
        return value

    if not isinstance(payload, dict) or payload.get("format") != "horas" or type(payload.get("version")) is not int or payload["version"] not in (1, 2):
        raise ValueError("La copia no tiene un formato compatible con Horas.")
    try:
        version = payload["version"]
        pref = payload["settings"]
        prefs = (integer(pref["default_minutes"], 15, 1440, 15), integer(pref["default_rate_cents"], 0, 1000000),
                 frequency_value(pref["payment_frequency"]) if version == 2 else "monthly")
        raw_weeks = payload["weeks"] if version == 2 else []
        if not all(isinstance(x, list) for x in (payload["months"], payload["entries"], raw_weeks)) or len(payload["months"]) > 1212 or len(payload["entries"]) > 37000 or len(raw_weeks) > 5400:
            raise ValueError("La copia contiene demasiados registros o un formato incorrecto.")
        months, entries, weeks, seen_months, seen_days, seen_weeks = [], [], [], {}, set(), set()
        for row in payload["months"]:
            month = month_value(row["month"])
            if month in seen_months:
                raise ValueError("La copia contiene meses duplicados.")
            cents, paid = integer(row["rate_cents"], 0, 1000000), integer(row["paid"], 0, 1)
            seen_months[month] = (cents, paid)
            months.append((month, cents, paid))
        for row in raw_weeks:
            week = week_value(row["week"])
            if week in seen_weeks:
                raise ValueError("La copia contiene semanas duplicadas.")
            seen_weeks.add(week)
            weeks.append((week, integer(row["rate_cents"], 0, 1000000)))
        for row in payload["entries"]:
            day = day_value(row["day"])
            if day in seen_days or day[:7] not in seen_months:
                raise ValueError("La copia contiene días duplicados o sin mes asociado.")
            note = row["note"]
            if not isinstance(note, str) or len(note) > 500:
                raise ValueError("La copia contiene una nota no válida.")
            seen_days.add(day)
            cents = integer(row["rate_cents"], 0, 1000000) if version == 2 else seen_months[day[:7]][0]
            paid = integer(row["paid"], 0, 1) if version == 2 else seen_months[day[:7]][1]
            entries.append((day, day[:7], integer(row["minutes"], 15, 1440, 15), note, cents, paid))
        return prefs, months, weeks, entries
    except (KeyError, TypeError):
        raise ValueError("La copia está incompleta o tiene un formato incorrecto.") from None
