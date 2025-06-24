from datetime import datetime

def format_duration(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours == 0:
        return f"{minutes:02}:{secs:02}"
    else:
        return f"{hours}:{minutes:02}:{secs:02}"

def format_datetime_pretty(value):
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%b %d, %Y %-I:%M %p")  # e.g., Jun 19, 2025 09:01 PM
    except Exception:
        return value  # Fallback if something goes wrong

def format_kilometers(meters):
    try:
        if meters == 0:
            return "--"
        km = float(meters) / 1000
        return f"{km:.2f} km"
    except (ValueError, TypeError):
        return meters
    
def register_filters(app):
    app.jinja_env.filters['format_duration'] = format_duration
    app.jinja_env.filters["pretty_datetime"] = format_datetime_pretty
    app.jinja_env.filters["km"] = format_kilometers