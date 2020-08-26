def human_time(time_secs, compact=False):
    label = lambda s: s[0] if compact else ' '+s
    days = int(time_secs // 86400)
    hours = int(time_secs // 3600 % 24)
    minutes = int(time_secs // 60 % 60)
    seconds = int(time_secs % 60)
    parts = []
    if days > 0:
        parts.append('{}{}'.format(days, label('days')))
    if days > 0 or hours > 0:
        parts.append('{}{}'.format(hours, label('hours')))
    if days > 0 or hours > 0 or minutes > 0:
        parts.append('{}{}'.format(minutes, label('minutes')))
    parts.append('{}{}'.format(seconds, label('seconds')))
    return ', '.join(parts)
