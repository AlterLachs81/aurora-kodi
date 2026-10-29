# -*- coding: utf-8 -*-
"""Aurora: independent Netflix navigation for Kodi."""
import base64
import json
import os
import sys
from urllib.parse import parse_qs, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib.aurora.auth_key import AuthenticationKeyError, decode_authentication_key
from resources.lib.aurora.catalog import (
    episodes, home_sections, search as search_videos, seasons, videos,
)
from resources.lib.aurora.netflix_client import NetflixClient, NetflixConnectionError
from resources.lib.aurora.player import resolve_netflix
from resources.lib.aurora.session import clear_session, load_cookies, save_cookies


ADDON = xbmcaddon.Addon()
BASE = sys.argv[0]
HANDLE = int(sys.argv[1])
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
STATE_FILE = os.path.join(PROFILE, 'aurora.json')
PAGE_SIZE = 40


def _query():
    raw = sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith('?') else ''
    return {key: values[-1] for key, values in parse_qs(raw, keep_blank_values=True).items()}


def _url(**params):
    return BASE + '?' + urlencode(params)


def _log(message, level=xbmc.LOGINFO):
    xbmc.log('Aurora: ' + str(message), level)


def _empty_state():
    return {'favorites': []}


def read_state():
    try:
        with xbmcvfs.File(STATE_FILE) as handle:
            value = json.loads(handle.read())
        if isinstance(value, dict):
            value.setdefault('favorites', [])
            return value
    except Exception as exc:
        _log('Could not read local state: {}'.format(exc), xbmc.LOGWARNING)
    return _empty_state()


def write_state(state):
    xbmcvfs.mkdirs(PROFILE)
    with xbmcvfs.File(STATE_FILE, 'w') as handle:
        handle.write(json.dumps(state, ensure_ascii=False))


def _encode_entry(entry):
    payload = json.dumps(entry, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(payload).decode('ascii')


def _decode_entry(value):
    return json.loads(base64.urlsafe_b64decode(value.encode('ascii')).decode('utf-8'))


def _set_video_info(item, entry):
    info = {}
    for source, destination in (('plot', 'plot'), ('year', 'year'), ('duration', 'duration')):
        if entry.get(source):
            info[destination] = entry[source]
    info['title'] = entry['label']
    item.setInfo('video', info)
    if entry.get('image'):
        item.setArt({'thumb': entry['image'], 'poster': entry['image'], 'icon': entry['image']})


def _favorite_context(entry):
    favorites = read_state()['favorites']
    is_saved = any(item.get('id') == entry.get('id') for item in favorites)
    label = 'Aus Aurora-Favoriten entfernen' if is_saved else 'Zu Aurora-Favoriten hinzufügen'
    command = _url(action='toggle_favorite', entry=_encode_entry(entry))
    return [(label, 'RunPlugin({})'.format(command))]


def _add_entry(entry):
    item = xbmcgui.ListItem(label=entry['label'])
    _set_video_info(item, entry)
    item.addContextMenuItems(_favorite_context(entry))
    if entry.get('type') == 'show':
        item.setProperty('IsPlayable', 'false')
        item_url = _url(action='browse_seasons', show_id=entry['id'], title=entry['label'])
        is_folder = True
    elif entry.get('type') == 'season':
        item.setProperty('IsPlayable', 'false')
        item_url = _url(action='browse_episodes', season_id=entry['id'], title=entry['label'])
        is_folder = True
    else:
        item.setProperty('IsPlayable', 'true')
        item_url = _url(action='play', entry=_encode_entry(entry))
        is_folder = False
    xbmcplugin.addDirectoryItem(
        HANDLE,
        item_url,
        item,
        isFolder=is_folder,
    )


def _add_message(label, message):
    item = xbmcgui.ListItem(label=label)
    item.setInfo('video', {'title': label, 'plot': message})
    xbmcplugin.addDirectoryItem(HANDLE, _url(action='message', text=message), item, isFolder=False)


def _finish(title, succeeded=True, content='videos'):
    xbmcplugin.setPluginCategory(HANDLE, title)
    xbmcplugin.setContent(HANDLE, content)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.endOfDirectory(HANDLE, succeeded=succeeded, cacheToDisc=False)


def show_home():
    title = 'A U R O R A'
    if load_cookies():
        try:
            for section in home_sections():
                item = xbmcgui.ListItem(label=section['title'])
                item.setInfo('video', {'title': section['title']})
                xbmcplugin.addDirectoryItem(
                    HANDLE,
                    _url(action='browse_catalog', list_id=section['id'], title=section['title']),
                    item,
                    isFolder=True,
                )
        except NetflixConnectionError as exc:
            _add_message('Netflix-Katalog nicht verfügbar', str(exc))
    else:
        _add_message(
            'Noch nicht angemeldet',
            'Importiere deinen NFAuthentication.key-Schlüssel. Aurora prüft die Sitzung direkt bei Netflix.',
        )

    session_label = 'Aurora-Sitzung löschen' if load_cookies() else 'Netflix-Schlüssel importieren'
    session_action = 'logout' if load_cookies() else 'import_auth_key'
    session_item = xbmcgui.ListItem(label=session_label)
    session_item.setInfo('video', {'title': session_label})
    xbmcplugin.addDirectoryItem(HANDLE, _url(action=session_action), session_item, isFolder=False)

    favorite_item = xbmcgui.ListItem(label='Aurora-Favoriten')
    favorite_item.setInfo('video', {'title': 'Aurora-Favoriten'})
    xbmcplugin.addDirectoryItem(HANDLE, _url(action='favorites'), favorite_item, isFolder=True)
    search_item = xbmcgui.ListItem(label='Netflix-Suche')
    search_item.setInfo('video', {'title': 'Netflix-Suche'})
    xbmcplugin.addDirectoryItem(HANDLE, _url(action='search'), search_item, isFolder=False)
    _finish(title, content='files')


def _as_entry(value):
    return {
        'id': str(value['id']),
        'label': value['title'],
        'path': 'netflix://video/{}'.format(value['id']),
        'image': value.get('image') or '',
        'plot': value.get('plot') or '',
        'year': value.get('year') or '',
        'duration': value.get('runtime') or 0,
        'type': value.get('type') or '',
    }


def _show_entries(title, entries, offset=0, local=False, list_id=''):
    offset = max(0, int(offset))
    page = entries[offset:offset + PAGE_SIZE] if local else entries
    for entry in page:
        _add_entry(entry)
    if local:
        has_more = False
    else:
        has_more = len(entries) == PAGE_SIZE
    if offset:
        previous = xbmcgui.ListItem(label='← Vorherige Seite')
        target = (_url(action='favorites', offset=max(0, offset - PAGE_SIZE)) if local else
                  _url(action='browse_catalog', list_id=list_id, title=title,
                       offset=max(0, offset - PAGE_SIZE)))
        xbmcplugin.addDirectoryItem(HANDLE, target, previous, isFolder=True)
    if has_more:
        next_item = xbmcgui.ListItem(label='Nächste Seite →')
        target = _url(action='browse_catalog', list_id=list_id, title=title,
                      offset=offset + PAGE_SIZE)
        xbmcplugin.addDirectoryItem(HANDLE, target, next_item, isFolder=True)
    _finish(title)


def _show_catalog_list(list_id, title, offset=0):
    try:
        entries = [_as_entry(value) for value in videos(list_id, start=offset, count=PAGE_SIZE)]
        _show_entries(title, entries, offset=offset, local=False, list_id=list_id)
    except NetflixConnectionError as exc:
        _log('Catalog request failed: {}'.format(exc), xbmc.LOGWARNING)
        _add_message('Netflix-Liste nicht abrufbar', str(exc))
        _finish(title, succeeded=False)


def _show_seasons(show_id, title):
    try:
        entries = []
        for value in seasons(show_id):
            entries.append({
                'id': value['id'], 'label': value['title'], 'path': 'netflix://season/{}'.format(value['id']),
                'image': value.get('image', ''), 'plot': '', 'year': '', 'duration': 0, 'type': 'season',
            })
        _show_entries(title, entries, local=True)
    except NetflixConnectionError as exc:
        _add_message('Staffeln nicht abrufbar', str(exc))
        _finish(title, succeeded=False)


def _show_episodes(season_id, title, offset=0):
    try:
        entries = []
        for value in episodes(season_id, start=offset, count=PAGE_SIZE):
            entries.append(_as_entry(value))
        _show_entries(title, entries, local=True)
    except NetflixConnectionError as exc:
        _add_message('Episoden nicht abrufbar', str(exc))
        _finish(title, succeeded=False)


def _show_favorites(offset=0):
    entries = read_state()['favorites']
    _show_entries('Aurora-Favoriten', entries, offset=offset, local=True)


def _search_catalog():
    term = xbmcgui.Dialog().input('Netflix durchsuchen')
    if not term or not term.strip():
        _finish('Netflix-Suche')
        return
    try:
        entries = [_as_entry(value) for value in search_videos(term.strip())]
        _show_entries('Suche: ' + term.strip(), entries, local=True)
    except NetflixConnectionError as exc:
        _add_message('Suche fehlgeschlagen', str(exc))
        _finish('Netflix-Suche', succeeded=False)


def _toggle_favorite(encoded_entry):
    entry = _decode_entry(encoded_entry)
    state = read_state()
    current = state['favorites']
    if any(item.get('id') == entry.get('id') for item in current):
        state['favorites'] = [item for item in current if item.get('id') != entry.get('id')]
        message = 'Aus Aurora-Favoriten entfernt'
    else:
        state['favorites'] = [entry] + current
        state['favorites'] = state['favorites'][:200]
        message = 'Zu Aurora-Favoriten hinzugefügt'
    write_state(state)
    xbmcgui.Dialog().notification('Aurora', message)
    xbmc.executebuiltin('Container.Refresh')


def _import_authentication_key():
    dialog = xbmcgui.Dialog()
    key_path = dialog.browse(1, 'NFAuthentication.key auswählen', 'files', '.key')
    if not key_path:
        return
    pin = dialog.input('PIN des Authentifizierungsschlüssels', type=xbmcgui.INPUT_NUMERIC)
    if not pin:
        return
    try:
        with xbmcvfs.File(key_path) as handle:
            cookies = decode_authentication_key(handle.read(), pin)
        NetflixClient(cookies).check_session()
        save_cookies(cookies)
    except (AuthenticationKeyError, NetflixConnectionError) as exc:
        dialog.ok('Aurora', str(exc))
        return
    except Exception as exc:
        _log('Authentication key import failed: {}'.format(exc), xbmc.LOGWARNING)
        dialog.ok('Aurora', 'Die Schlüsseldatei konnte nicht gelesen werden.')
        return
    dialog.ok('Aurora', 'Aurora hat die Sitzung direkt bei Netflix geprüft und gespeichert.')


def _dispatch(params):
    action = params.get('action', 'home')
    if action == 'browse_catalog':
        _show_catalog_list(params.get('list_id', ''), params.get('title', 'Netflix'),
                           params.get('offset', 0))
    elif action == 'browse_seasons':
        _show_seasons(params.get('show_id', ''), params.get('title', 'Staffeln'))
    elif action == 'browse_episodes':
        _show_episodes(params.get('season_id', ''), params.get('title', 'Episoden'),
                       params.get('offset', 0))
    elif action == 'favorites':
        _show_favorites(params.get('offset', 0))
    elif action == 'search':
        _search_catalog()
    elif action == 'import_auth_key':
        _import_authentication_key()
        show_home()
    elif action == 'logout':
        clear_session()
        xbmcgui.Dialog().notification('Aurora', 'Aurora-Sitzung gelöscht')
        show_home()
    elif action == 'toggle_favorite':
        _toggle_favorite(params['entry'])
    elif action == 'play':
        resolve_netflix(HANDLE, _decode_entry(params['entry']))
    elif action == 'title_info':
        entry = _decode_entry(params['entry'])
        xbmcgui.Dialog().ok(entry['label'], entry.get('plot') or 'Weitere Titelinformationen sind noch nicht verfügbar.')
        _finish(entry['label'])
    elif action == 'message':
        xbmcgui.Dialog().ok('Aurora', params.get('text', ''))
        _finish('Aurora')
    else:
        show_home()


def main():
    try:
        _dispatch(_query())
    except Exception as exc:
        _log('Uncaught error: {}'.format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().notification('Aurora', 'Fehler: {}'.format(exc), xbmcgui.NOTIFICATION_ERROR)
        try:
            _finish('Aurora', succeeded=False)
        except Exception:
            pass


if __name__ == '__main__':
    main()
