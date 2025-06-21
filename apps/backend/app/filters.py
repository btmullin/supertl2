def format_duration(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours}:{minutes:02}:{secs:02}"

def register_filters(app):
    app.jinja_env.filters['format_duration'] = format_duration