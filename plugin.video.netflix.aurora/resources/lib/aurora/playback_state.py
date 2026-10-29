# -*- coding: utf-8 -*-
"""Small local hand-off store shared by Aurora's plugin and service process."""
import json
import os
import threading

import xbmcvfs


_LOCK = threading.RLock()


def _path():
    import xbmcaddon
    profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
    return os.path.join(profile, 'playback_state.json')


def _read_all():
    path = _path()
    if not xbmcvfs.exists(path):
        return {}
    try:
        with xbmcvfs.File(path) as handle:
            value = json.loads(handle.read())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_all(value):
    path = _path()
    xbmcvfs.mkdirs(os.path.dirname(path))
    with xbmcvfs.File(path, 'w') as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def create(token, entry):
    with _LOCK:
        state = _read_all()
        state[token] = {
            'video_id': str(entry['id']),
            'title': str(entry.get('label') or ''),
            'image': str(entry.get('image') or ''),
        }
        _write_all(state)


def get(token):
    with _LOCK:
        return _read_all().get(token)


def save_manifest(token, manifest, xid):
    with _LOCK:
        state = _read_all()
        if token not in state:
            raise KeyError('Aurora-Wiedergabesitzung ist abgelaufen.')
        state[token]['manifest'] = manifest
        state[token]['xid'] = str(xid)
        _write_all(state)


def clear():
    path = _path()
    with _LOCK:
        if xbmcvfs.exists(path):
            xbmcvfs.delete(path)
