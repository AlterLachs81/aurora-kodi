# -*- coding: utf-8 -*-
"""Aurora: a native Kodi navigation layer for Netflix."""
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


ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
BASE = sys.argv[0]
HANDLE = int(sys.argv[1])
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
STATE_FILE = os.path.join(PROFILE, 'aurora.json')
BACKEND_ID = 'plugin.video.netflix'
BACKEND_ROOT = 'plugin://plugin.video.netflix/'

# These are CastagnaIT's public Kodi plugin routes. Aurora owns the menus,
# navigation, local favorites and history; Kodi delegates Netflix session and
# playback to the installed backend.
BACKEND_SECTIONS = (
    ('Entdecken', 'plugin://plugin.video.netflix/directory/home'),
    ('Meine Netflix-Liste', 'plugin://plugin.video.netflix/directory/video_list_sorted/myList'),
    ('Weitersehen', 'plugin://plugin.video.netflix/directory/video_list/continueWatching'),
    ('Filme', 'plugin://plugin.video.netflix/directory/genres/movies/34399'),
    ('Serien', 'plugin://plugin.video.netflix/directory/genres/tvshows/83'),
    ('Genres', 'plugin://plugin.video.netflix/directory/genres/genres'),
    ('Neu und beliebt', 'plugin://plugin.video.netflix/directory/category_list/newAndPopular'),
)


def _query():
    raw = sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith('?') else ''
    return {key: values[-1] for key, values in parse_qs(raw, keep_blank_values=True).items()}


def _url(**params):
    return BASE + '?' + urlencode(params)


def _log(message, level=xbmc.LOGINFO):
    xbmc.log('Aurora: ' + str(message), level)


def _empty_state():
    return {'favorites': [], 'recent': []}


def read_state():
    try:
        with xbmcvfs.File(STATE_FILE) as handle:
            value = json.loads(handle.read())
        if isinstance(value, dict):
            value.setdefault('favorites', [])
            value.setdefault('recent', [])
            return value
    except Exception as exc:
        _log('could not read local state: {}'.format(exc), xbmc.LOGWARNING)
    return _empty_state()


def write_state(state):
    xbmcvfs.mkdirs(PROFILE)
    with xbmcvfs.File(STATE_FILE, 'w') as handle:
        handle.write(json.dumps(state, ensure_ascii=False))


def _backend_available():
    return xbmc.getCondVisibility('System.HasAddon({})'.format(BACKEND_ID))


def _jsonrpc_directory(path):
    request = {
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'Files.GetDirectory',
        'params': {
            'directory': path,
            'media': 'video',
            'properties': ['title', 'thumbnail', 'art', 'plot', 'year', 'duration', 'filetype'],
        },
    }
    try:
        answer = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    except Exception as exc:
        raise RuntimeError('Kodi could not read the Netflix list: {}'.format(exc))
    if answer.get('error'):
        raise RuntimeError(answer['error'].get('message', str(answer['error'])))
    return answer.get('result', {}).get('files', [])


def _set_video_info(item, entry):
    info = {}
    for source, destination in (
        ('label', 'title'),
        ('plot', 'plot'),
        ('year', 'year'),
        ('duration', 'duration'),
    ):
        if entry.get(source):
            info[destination] = entry[source]
    if info:
        item.setInfo('video', info)
    art = entry.get('image')
    if art:
        item.setArt({'thumb': art, 'poster': art, 'icon': art})


def _entry_from_backend(value):
    art = value.get('art') or {}
    image = (art.get('poster') or art.get('thumb') or value.get('thumbnail') or
             art.get('landscape') or art.get('fanart') or '')
    path = value.get('file') or ''
    if not path:
        return None
    label = value.get('label') or value.get('title') or 'Ohne Titel'
    return {
        'label': label,
        'path': path,
        'folder': value.get('filetype') == 'directory',
        'image': image,
        'plot': value.get('plot') or '',
        'year': value.get('year') or '',
        'duration': value.get('duration') or 0,
    }


def _encode_entry(entry):
    payload = json.dumps(entry, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(payload).decode('ascii')


def _decode_entry(value):
    return json.loads(base64.urlsafe_b64decode(value.encode('ascii')).decode('utf-8'))


def _favorite_context(entry):
    state = read_state()
    paths = {item.get('path') for item in state['favorites']}
    is_saved = entry['path'] in paths
    command = _url(action='toggle_favorite', entry=_encode_entry(entry))
    label = 'Aus Aurora-Favoriten entfernen' if is_saved else 'Zu Aurora-Favoriten hinzufügen'
    return [(label, 'RunPlugin({})'.format(command))]


def _add_entry(entry):
    if entry['folder']:
        item_url = _url(action='browse', path=entry['path'], title=entry['label'])
    else:
        item_url = _url(action='play', path=entry['path'], entry=_encode_entry(entry))
    item = xbmcgui.ListItem(label=entry['label'])
    _set_video_info(item, entry)
    item.addContextMenuItems(_favorite_context(entry))
    xbmcplugin.addDirectoryItem(HANDLE, item_url, item, isFolder=entry['folder'])


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
    if not _backend_available():
        _add_message(
            'Netflix-Datenquelle fehlt',
            'Für Katalog und Wiedergabe wird das Netflix-Add-on plugin.video.netflix benötigt. '
            'Aurora selbst bleibt auch ohne dieses Add-on startbar.',
        )
    for label, path in BACKEND_SECTIONS:
        item = xbmcgui.ListItem(label=label)
        item.setInfo('video', {'title': label})
        xbmcplugin.addDirectoryItem(
            HANDLE,
            _url(action='browse', path=path, title=label),
            item,
            isFolder=True,
        )
    for label, action in (
        ('Suche', 'search'),
        ('Aurora-Favoriten', 'favorites'),
        ('Zuletzt gestartet', 'recent'),
    ):
        item = xbmcgui.ListItem(label=label)
        item.setInfo('video', {'title': label})
        xbmcplugin.addDirectoryItem(HANDLE, _url(action=action), item, isFolder=True)
    if _backend_available():
        backend_item = xbmcgui.ListItem(label='Netflix-Add-on direkt öffnen')
        xbmcplugin.addDirectoryItem(
            HANDLE,
            _url(action='open_backend'),
            backend_item,
            isFolder=False,
        )
    _finish(title, content='files')


def _show_local_list(title, key, offset=0):
    entries = read_state().get(key, [])
    _show_entries(title, entries, offset)


def _show_backend_list(path, title, offset=0):
    if not _backend_available():
        _add_message('Netflix-Datenquelle fehlt', 'Installiere zuerst plugin.video.netflix.')
        _finish(title, succeeded=False)
        return
    try:
        entries = [_entry_from_backend(value) for value in _jsonrpc_directory(path)]
        entries = [entry for entry in entries if entry]
    except Exception as exc:
        _log('listing failed for {}: {}'.format(path, exc), xbmc.LOGWARNING)
        _add_message('Netflix-Liste nicht abrufbar', str(exc))
        _finish(title, succeeded=False)
        return
    _show_entries(title, entries, offset, source_path=path)


def _show_entries(title, entries, offset=0, source_path=None):
    page_size = 40
    offset = max(0, int(offset))
    page = entries[offset:offset + page_size]
    for entry in page:
        _add_entry(entry)
    local_section = {'Aurora-Favoriten': 'favorites', 'Zuletzt gestartet': 'recent'}.get(title)
    if offset:
        previous = xbmcgui.ListItem(label='← Vorherige Seite')
        if local_section:
            previous_url = _url(action='browse_local', section=local_section, title=title,
                                offset=max(0, offset - page_size))
        else:
            previous_url = _url(action='browse', path=source_path or _query().get('path', ''),
                                title=title, offset=max(0, offset - page_size))
        xbmcplugin.addDirectoryItem(HANDLE, previous_url, previous, isFolder=True)
    if offset + page_size < len(entries):
        next_item = xbmcgui.ListItem(label='Nächste Seite →')
        if local_section:
            next_params = {
                'action': 'browse_local',
                'section': local_section,
                'title': title,
                'offset': offset + page_size,
            }
        else:
            next_params = {
                'action': 'browse',
                'path': source_path or _query().get('path', ''),
                'title': title,
                'offset': offset + page_size,
            }
        xbmcplugin.addDirectoryItem(HANDLE, BASE + '?' + urlencode(next_params), next_item, isFolder=True)
    _finish(title)


def _remember(entry):
    state = read_state()
    state['recent'] = [entry] + [old for old in state['recent'] if old.get('path') != entry.get('path')]
    state['recent'] = state['recent'][:40]
    write_state(state)


def _toggle_favorite(encoded_entry):
    entry = _decode_entry(encoded_entry)
    state = read_state()
    favorites = state['favorites']
    if any(item.get('path') == entry.get('path') for item in favorites):
        state['favorites'] = [item for item in favorites if item.get('path') != entry.get('path')]
        message = 'Aus Aurora-Favoriten entfernt'
    else:
        state['favorites'] = [entry] + favorites
        state['favorites'] = state['favorites'][:200]
        message = 'Zu Aurora-Favoriten hinzugefügt'
    write_state(state)
    xbmcgui.Dialog().notification('Aurora', message)
    xbmc.executebuiltin('Container.Refresh')


def _run_search():
    if not _backend_available():
        xbmcgui.Dialog().ok('Aurora', 'Für Netflix-Suche und Katalog wird plugin.video.netflix benötigt.')
        return False
    term = xbmcgui.Dialog().input('Netflix durchsuchen')
    if not term or not term.strip():
        return False
    path = 'plugin://plugin.video.netflix/directory/search/search/?' + urlencode({'query': term.strip()})
    _show_backend_list(path, 'Suche: ' + term.strip())
    return True


def _dispatch(params):
    action = params.get('action', 'home')
    if action == 'browse':
        _show_backend_list(params.get('path', BACKEND_ROOT), params.get('title', 'Netflix'))
    elif action == 'browse_local':
        _show_local_list(params.get('title', 'Aurora-Favoriten'), params.get('section', 'favorites'),
                         params.get('offset', 0))
    elif action == 'favorites':
        _show_local_list('Aurora-Favoriten', 'favorites')
    elif action == 'recent':
        _show_local_list('Zuletzt gestartet', 'recent')
    elif action == 'search':
        if not _run_search():
            _finish('Suche')
    elif action == 'play':
        entry = _decode_entry(params['entry'])
        _remember(entry)
        target = params.get('path') or entry.get('path', '')
        item = xbmcgui.ListItem(path=target)
        item.setProperty('IsPlayable', 'true')
        xbmcplugin.setResolvedUrl(HANDLE, True, item)
    elif action == 'toggle_favorite':
        _toggle_favorite(params['entry'])
    elif action == 'open_backend':
        xbmc.executebuiltin('ActivateWindow(Videos,{})'.format(json.dumps(BACKEND_ROOT)))
    elif action == 'message':
        xbmcgui.Dialog().ok('Aurora', params.get('text', ''))
    else:
        show_home()


def main():
    try:
        params = _query()
        if params.get('action') in (None, '', 'home'):
            show_home()
        else:
            _dispatch(params)
    except Exception as exc:
        _log('uncaught error: {}'.format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().notification('Aurora', 'Fehler: {}'.format(exc), xbmcgui.NOTIFICATION_ERROR)
        try:
            _finish('Aurora', succeeded=False)
        except Exception:
            pass


if __name__ == '__main__':
    main()
