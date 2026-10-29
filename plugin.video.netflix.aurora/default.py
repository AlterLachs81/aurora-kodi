# -*- coding: utf-8 -*-
"""Aurora: original Kodi GUI; installed Netflix add-on provides catalogue and playback."""
import json
import os
import sys
from urllib.parse import urlencode
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

ADDON = xbmcaddon.Addon()
BASE = sys.argv[0]
HANDLE = int(sys.argv[1])
BACKEND = 'plugin://plugin.video.netflix/'
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
STATE_FILE = os.path.join(PROFILE, 'aurora.json')
W, H = 1280, 720
MEDIA = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media')
BG = 'FF0B101C'
PANEL = 'FF18243A'
WHITE = 'FFF5F7FB'
MUTED = 'FF9EACC2'
ACCENT = 'FF60E6D1'


def read_state():
    try:
        with xbmcvfs.File(STATE_FILE) as f:
            data = json.loads(f.read())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {'favorites': [], 'recent': []}


def write_state(data):
    xbmcvfs.mkdirs(PROFILE)
    with xbmcvfs.File(STATE_FILE, 'w') as f:
        f.write(json.dumps(data, ensure_ascii=False))


def rpc(method, params):
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
    answer = json.loads(xbmc.executeJSONRPC(json.dumps(payload)))
    if 'error' in answer:
        raise RuntimeError(str(answer['error']))
    return answer.get('result', {})


def directory(path):
    result = rpc('Files.GetDirectory', {'directory': path, 'media': 'video',
        'properties': ['title', 'thumbnail', 'art', 'plot', 'year', 'duration', 'file', 'filetype']})
    entries = []
    for f in result.get('files', []):
        target = f.get('file', '')
        if not target:
            continue
        art = f.get('art') or {}
        entries.append({'label': f.get('label') or f.get('title') or 'Ohne Titel',
            'path': target, 'folder': f.get('filetype') == 'directory',
            'image': art.get('poster') or art.get('thumb') or f.get('thumbnail') or art.get('fanart') or '',
            'plot': f.get('plot') or '', 'year': f.get('year') or ''})
    return entries


def remember(entry):
    state = read_state()
    state['recent'] = [entry] + [x for x in state['recent'] if x.get('path') != entry['path']]
    state['recent'] = state['recent'][:30]
    write_state(state)


def open_entry(entry):
    path = entry['path']
    if entry.get('folder'):
        return path
    remember(entry)
    xbmc.executebuiltin('PlayMedia("%s")' % path.replace('"', '%22'))
    return None


class Aurora(xbmcgui.WindowDialog):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.entries = []
        self.current = BACKEND
        self.mode = 'browse'
        self.page = 0
        self.selected = 0
        self.controls = []
        self.tile_buttons = {}
        self.title = None
        self.subtitle = None
        self.status = None
        self.busy = False

    def add(self, control):
        self.addControl(control)
        self.controls.append(control)
        return control

    def label(self, x, y, width, height, text, size='font20', color=WHITE):
        return self.add(xbmcgui.ControlLabel(x, y, width, height, text,
            font=size, textColor=color))

    def button(self, x, y, width, height, text, action, idx=None):
        b = self.add(xbmcgui.ControlButton(x, y, width, height, text,
            font='font16', textColor=WHITE, focusedColor='FF0B101C',
            focusTexture=os.path.join(MEDIA, 'button-focus.png'), noFocusTexture=os.path.join(MEDIA, 'button-nofocus.png'),
            alignment=2))
        self.tile_buttons[b.getId()] = (action, idx)
        return b

    def onInit(self):
        self.add(xbmcgui.ControlImage(0, 0, W, H, os.path.join(MEDIA, 'background.png')))
        self.label(50, 24, 650, 52, 'A U R O R A', 'font30', ACCENT)
        self.label(51, 74, 900, 28, 'NETFLIX  /  DEINE BIBLIOTHEK', 'font13', MUTED)
        nav = [('Start', 'home'), ('Suche', 'search'), ('Merkliste', 'favorites'),
               ('Zuletzt', 'recent'), ('Netflix', 'root'), ('Beenden', 'exit')]
        for i, (name, action) in enumerate(nav):
            self.button(45 + i * 193, 121, 178, 43, name, action)
        self.title = self.label(51, 188, 1110, 45, '', 'font24')
        self.subtitle = self.label(52, 236, 1110, 30, '', 'font13', MUTED)
        self.status = self.label(51, 665, 1150, 30, '', 'font13', MUTED)
        self.load(BACKEND, 'Entdecken')

    def load(self, path, title, push=False):
        if self.busy:
            return
        self.busy = True
        if push:
            self.stack.append((self.current, self.title.getLabel() if self.title else 'Entdecken', self.mode))
        self.current, self.mode, self.page = path, 'browse', 0
        self.status.setLabel('Lade Netflix-Katalog ...')
        try:
            self.entries = directory(path)
            self.title.setLabel(title)
            self.subtitle.setLabel('%s Einträge  •  Cover auswählen zum Öffnen' % len(self.entries))
            self.status.setLabel('OK / Enter: öffnen   •   Kontextmenü: merken   •   Zurück: vorherige Ansicht')
        except Exception as e:
            xbmc.log('Aurora browse error: %s' % e, xbmc.LOGWARNING)
            self.entries = []
            self.title.setLabel('Katalog nicht abrufbar')
            self.subtitle.setLabel('Die Kodi-JSON-RPC-Schnittstelle konnte diese Liste nicht lesen.')
            self.status.setLabel('Netflix direkt öffnen über die Schaltfläche oben.')
        self.busy = False
        self.draw_tiles()

    def show_local(self, name, key):
        self.mode, self.page = key, 0
        self.entries = read_state().get(key, [])
        self.title.setLabel(name)
        self.subtitle.setLabel('%s gespeicherte Titel' % len(self.entries))
        self.draw_tiles()

    def draw_tiles(self):
        for control in getattr(self, 'tiles', []):
            self.removeControl(control)
        self.tiles = []
        self.tile_buttons = {k: v for k, v in self.tile_buttons.items() if v[0] not in ('tile', 'prev', 'next', 'fallback')}
        start = self.page * 10
        page_entries = self.entries[start:start + 10]
        for i, entry in enumerate(page_entries):
            x = 51 + (i % 5) * 241
            y = 281 + (i // 5) * 177
            image = entry.get('image') or 'DefaultFolder.png'
            try:
                cover = xbmcgui.ControlImage(x + 3, y, 112, 128, image, aspectRatio=2)
                self.addControl(cover)
                self.tiles.append(cover)
            except Exception:
                pass
            name = entry.get('label', 'Ohne Titel')
            if len(name) > 29:
                name = name[:27] + '…'
            btn = self.button(x + 119, y + 10, 113, 106, name, 'tile', start + i)
            self.tiles.append(btn)
        if self.page:
            self.tiles.append(self.button(970, 644, 92, 39, '◀', 'prev'))
        if start + 10 < len(self.entries):
            self.tiles.append(self.button(1070, 644, 92, 39, '▶', 'next'))
        if not self.entries:
            self.tiles.append(self.button(53, 298, 340, 53, 'Netflix-Katalog direkt öffnen', 'fallback'))
        if page_entries:
            self.setFocus(self.tiles[1] if len(self.tiles) > 1 else self.tiles[0])

    def activate(self, entry):
        if entry.get('folder'):
            self.load(entry['path'], entry['label'], push=True)
        else:
            open_entry(entry)

    def favorite(self, entry):
        state = read_state()
        favorites = state.get('favorites', [])
        found = any(x.get('path') == entry['path'] for x in favorites)
        state['favorites'] = ([x for x in favorites if x.get('path') != entry['path']]
                              if found else favorites + [entry])
        write_state(state)
        xbmcgui.Dialog().notification('Aurora', 'Aus Merkliste entfernt' if found else 'Zur Merkliste hinzugefügt')
        if self.mode == 'favorites':
            self.show_local('Deine Merkliste', 'favorites')

    def onClick(self, controlId):
        action, index = self.tile_buttons.get(controlId, ('', None))
        if action == 'exit':
            self.close()
        elif action == 'home':
            self.stack = []
            self.load(BACKEND, 'Entdecken')
        elif action == 'root':
            self.close()
            xbmc.executebuiltin('ActivateWindow(Videos,"%s",return)' % BACKEND)
        elif action == 'fallback':
            self.close()
            xbmc.executebuiltin('ActivateWindow(Videos,"%s",return)' % self.current)
        elif action == 'favorites':
            self.show_local('Deine Merkliste', 'favorites')
        elif action == 'recent':
            self.show_local('Zuletzt gestartet', 'recent')
        elif action == 'search':
            term = xbmcgui.Dialog().input('Netflix durchsuchen')
            if term:
                # Search is delegated to the backend's native search UI; no undocumented URL guessing.
                self.close()
                xbmc.executebuiltin('ActivateWindow(Videos,"%s",return)' % BACKEND)
                xbmcgui.Dialog().notification('Aurora', 'Suche im Netflix-Menü öffnen: ' + term)
        elif action == 'tile' and index is not None and index < len(self.entries):
            self.activate(self.entries[index])
        elif action == 'prev':
            self.page = max(0, self.page - 1)
            self.draw_tiles()
        elif action == 'next':
            self.page += 1
            self.draw_tiles()

    def onAction(self, action):
        code = action.getId()
        if code in (9, 10, 92, 216):
            if self.stack:
                path, title, mode = self.stack.pop()
                self.load(path, title)
            else:
                self.close()
        elif code in (117, 101):
            focus = self.getFocusId()
            action_name, index = self.tile_buttons.get(focus, ('', None))
            if action_name == 'tile' and index is not None and index < len(self.entries):
                self.favorite(self.entries[index])


def native():
    li = xbmcgui.ListItem('Aurora öffnen')
    xbmcplugin.addDirectoryItem(HANDLE, BASE + '?open=1', li, False)
    xbmcplugin.endOfDirectory(HANDLE)


def main():
    if not xbmc.getCondVisibility('System.HasAddon(plugin.video.netflix)'):
        xbmcgui.Dialog().ok('Aurora', 'Das bereits funktionierende Netflix-Add-on wird benötigt.')
        return
    if 'open=1' not in (sys.argv[2] if len(sys.argv) > 2 else ''):
        # Kodi invokes the plugin via its folder; immediately display the custom window.
        pass
    window = Aurora()
    window.doModal()
    del window
    native()


if __name__ == '__main__':
    main()
