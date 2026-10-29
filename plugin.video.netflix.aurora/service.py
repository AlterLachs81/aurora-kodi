# -*- coding: utf-8 -*-
"""Loopback-only HTTP bridge between InputStream Adaptive and Aurora MSL."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

import xbmc

from resources.lib.aurora.dash_manifest import ManifestError, convert_vod_to_mpd
from resources.lib.aurora.msl import MSLClient, MSLRequestError
from resources.lib.aurora.playback_state import get as get_playback_state, save_manifest
from resources.lib.aurora.profiles import enabled_profiles
from resources.lib.aurora.session import load_cookies
from resources.lib.aurora.netflix_client import NetflixClient, NetflixConnectionError


PORT = 8765
_LOG_PREFIX = 'Aurora playback service: '


def _msl_client():
    cookies = load_cookies()
    if not cookies:
        raise MSLRequestError('Bitte zuerst die Netflix-Sitzung in Aurora importieren.')
    netflix = NetflixClient(cookies)
    netflix.check_session()
    return MSLClient(
        cookies,
        netflix.esn,
        language=netflix.preferred_locale,
        client_info=netflix.client_info,
    )


class _PlaybackHandler(BaseHTTPRequestHandler):
    server_version = 'AuroraPlayback/0.1'
    sys_version = ''

    def log_message(self, fmt, *args):
        xbmc.log(_LOG_PREFIX + (fmt % args), xbmc.LOGDEBUG)

    def _reply(self, status, body, content_type='text/plain; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        parts = [part for part in urlsplit(self.path).path.split('/') if part]
        if len(parts) != 3 or parts[0] != 'aurora' or parts[1] not in ('manifest', 'license'):
            return None, None
        return parts[1], parts[2]

    def do_GET(self):
        route, token = self._route()
        if route != 'manifest':
            self._reply(404, b'Not found')
            return
        state = get_playback_state(token)
        if not state:
            self._reply(404, b'Playback session expired')
            return
        challenge = unquote(self.headers.get('challengeB64', '')).strip()
        session_id = self.headers.get('sessionId', '').strip()
        if not challenge or not session_id:
            self._reply(400, b'Widevine challenge/session data missing')
            return
        try:
            msl = _msl_client()
            manifest, xid = msl.licensed_manifest(
                state['video_id'], enabled_profiles(), challenge, session_id,
            )
            if isinstance(manifest, list) and len(manifest) == 1:
                manifest = manifest[0]
            if not isinstance(manifest, dict) or not manifest.get('video_tracks'):
                raise MSLRequestError('Netflix lieferte kein abspielbares Manifest.')
            save_manifest(token, manifest, xid)
            mpd = convert_vod_to_mpd(manifest)
        except (KeyError, MSLRequestError, NetflixConnectionError, ManifestError) as exc:
            self._reply(502, str(exc).encode('utf-8', errors='replace'))
            return
        except Exception as exc:
            xbmc.log(_LOG_PREFIX + 'Manifest request failed: ' + type(exc).__name__, xbmc.LOGERROR)
            self._reply(500, b'Aurora konnte das Manifest nicht verarbeiten.')
            return
        self._reply(200, mpd, 'application/dash+xml')

    def do_POST(self):
        route, token = self._route()
        if route != 'license':
            self._reply(404, b'Not found')
            return
        state = get_playback_state(token)
        if not state or not state.get('manifest') or not state.get('xid'):
            self._reply(409, b'Playback manifest is missing')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self._reply(400, b'Invalid content length')
            return
        if length <= 0 or length > 1024 * 1024:
            self._reply(413, b'Invalid challenge size')
            return
        license_data = self.rfile.read(length)
        try:
            license_response = _msl_client().licensed_video_response(
                state['manifest'], license_data, state['xid'],
            )
        except (MSLRequestError, NetflixConnectionError) as exc:
            self._reply(502, str(exc).encode('utf-8', errors='replace'))
            return
        except Exception as exc:
            xbmc.log(_LOG_PREFIX + 'License request failed: ' + type(exc).__name__, xbmc.LOGERROR)
            self._reply(500, b'Aurora konnte die Widevine-Lizenz nicht abrufen.')
            return
        self._reply(200, license_response, 'application/octet-stream')


def main():
    monitor = xbmc.Monitor()
    try:
        server = ThreadingHTTPServer(('127.0.0.1', PORT), _PlaybackHandler)
    except OSError as exc:
        xbmc.log(_LOG_PREFIX + 'Could not bind loopback port: ' + str(exc), xbmc.LOGERROR)
        return
    thread = threading.Thread(target=server.serve_forever, name='AuroraPlayback', daemon=True)
    thread.start()
    xbmc.log(_LOG_PREFIX + 'Listening on 127.0.0.1:{}'.format(PORT), xbmc.LOGINFO)
    try:
        while not monitor.abortRequested():
            if monitor.waitForAbort(1):
                break
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        xbmc.log(_LOG_PREFIX + 'Stopped', xbmc.LOGINFO)


if __name__ == '__main__':
    main()
