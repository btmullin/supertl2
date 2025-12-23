from datetime import date, timedelta

def start_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday

def week_offset_for_date(target: date, today: date | None = None) -> int:
    if today is None:
        today = date.today()
    base = start_of_week(today)
    tgt = start_of_week(target)
    return (tgt - base).days // 7
