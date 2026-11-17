import hashlib, json


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def dataset_dict(d):
    return {'id': d.id, 'name': d.name, 'source': d.source, 'rows': len(d.records), 'checksum': d.checksum, 'created_at': d.created_at}


def job_dict(j):
    return {k: getattr(j, k) for k in ['id', 'name', 'dataset_id', 'params', 'status', 'result', 'error', 'approved', 'created_at', 'finished_at']}


def report_dict(r):
    data = {k: getattr(r, k) for k in
            ['id', 'name', 'job_id', 'destination', 'interval_seconds',
             'next_run', 'enabled', 'schedule_mode', 'start_date']}
    versions = getattr(r, '_versions_cache', None)
    if versions is not None:
        data['versions'] = [version_dict(v) for v in versions]
    return data


def version_dict(v):
    return {
        'id': v.id, 'report_id': v.report_id, 'version_no': v.version_no,
        'timezone': v.timezone, 'workdays': v.config_dict()['workdays'],
        'handover_time': v.handover_time,
        'paused_dates': v.config_dict()['paused_dates'],
        'effective_from': v.effective_from, 'created_at': v.created_at,
        'created_by': v.created_by, 'note': v.note,
    }


def slot_dict(s):
    return {
        'id': s.id, 'report_id': s.report_id, 'version_id': s.version_id,
        'slot_key': s.slot_key, 'slot_date': s.slot_date,
        'local_time': s.local_time, 'scheduled_at': s.scheduled_at,
        'utc_offset_minutes': s.utc_offset_minutes, 'status': s.status,
        'dst_note': s.dst_note, 'last_error': s.last_error,
        'created_at': s.created_at, 'delivered_at': s.delivered_at,
    }


def delivery_dict(d):
    data = {k: getattr(d, k) for k in
            ['id', 'report_id', 'created_at', 'checksum', 'filename',
             'destination', 'slot_id', 'status', 'schedule_mode',
             'version_id', 'error']}
    return data
