# -*- coding: utf-8 -*-
"""Local storage for Aurora's imported Netflix session cookies."""
import json
import os

import xbmcvfs


def _session_path():
    import xbmcaddon
    profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
    return os.path.join(profile, 'netflix_session.json')


def save_cookies(cookies):
    path = _session_path()
    xbmcvfs.mkdirs(os.path.dirname(path))
    with xbmcvfs.File(path, 'w') as handle:
        handle.write(json.dumps({'cookies': cookies}, separators=(',', ':')))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_cookies():
    path = _session_path()
    if not xbmcvfs.exists(path):
        return []
    try:
        with xbmcvfs.File(path) as handle:
            value = json.loads(handle.read())
        cookies = value.get('cookies', []) if isinstance(value, dict) else []
        return cookies if isinstance(cookies, list) else []
    except (ValueError, OSError):
        return []


def msl_user_auth_data(cookies=None):
    """Build Netflix MSL cookie authentication data from Aurora's session."""
    cookie_values = {}
    for cookie in cookies if cookies is not None else load_cookies():
        if cookie.get('name') in ('NetflixId', 'SecureNetflixId'):
            cookie_values[cookie['name']] = cookie.get('value', '')
    netflix_id = cookie_values.get('NetflixId')
    secure_id = cookie_values.get('SecureNetflixId')
    if not netflix_id or not secure_id:
        raise ValueError('Die Sitzung enthält nicht beide Netflix-Anmelde-Cookies.')
    return {
        'scheme': 'NETFLIXID',
        'authdata': {
            'netflixid': netflix_id,
            'securenetflixid': secure_id,
        },
    }


def clear_session():
    path = _session_path()
    if xbmcvfs.exists(path):
        xbmcvfs.delete(path)
