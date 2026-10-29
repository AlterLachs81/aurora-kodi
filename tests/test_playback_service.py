import sys
import threading
import types
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

PLUGIN = Path(__file__).resolve().parents[1] / 'plugin.video.netflix.aurora'
sys.path.insert(0, str(PLUGIN))

xbmc_stub = sys.modules.setdefault('xbmc', types.ModuleType('xbmc'))
xbmc_stub.LOGDEBUG = 0
xbmc_stub.LOGERROR = 1
xbmc_stub.LOGINFO = 2
xbmc_stub.log = lambda *args, **kwargs: None

import service  # noqa: E402


class FakeMSLClient:
    def licensed_manifest(self, video_id, profiles, challenge, session_id):
        return {'video_tracks': [{'streams': []}]}, 'xid-test'

    def licensed_video_response(self, manifest, license_data, xid):
        if license_data != b'challenge!c2Vzc2lvbg==':
            raise AssertionError('License request body changed')
        return b'license-response'


class PlaybackServiceTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), service._PlaybackHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:{}/aurora'.format(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_manifest_callback_returns_dash(self):
        with patch.object(service, 'get_playback_state', return_value={'video_id': '42'}), \
                patch.object(service, '_msl_client', return_value=FakeMSLClient()), \
                patch.object(service, 'save_manifest') as save, \
                patch.object(service, 'convert_vod_to_mpd', return_value=b'<MPD/>'):
            request = Request(
                self.base + '/manifest/token',
                headers={'challengeB64': 'Y2hhbGxlbmdl', 'sessionId': 'session'},
            )
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), 'application/dash+xml')
                self.assertEqual(response.read(), b'<MPD/>')
            save.assert_called_once_with('token', {'video_tracks': [{'streams': []}]}, 'xid-test')

    def test_license_callback_returns_binary_license(self):
        state = {'manifest': {'links': {'license': {'href': 'https://license.invalid'}}}, 'xid': 'xid-test'}
        with patch.object(service, 'get_playback_state', return_value=state), \
                patch.object(service, '_msl_client', return_value=FakeMSLClient()):
            request = Request(
                self.base + '/license/token',
                data=b'challenge!c2Vzc2lvbg==',
                headers={'Content-Type': 'application/octet-stream'},
                method='POST',
            )
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), 'application/octet-stream')
                self.assertEqual(response.read(), b'license-response')

    def test_unknown_route_is_rejected(self):
        with self.assertRaises(Exception):
            urlopen(self.base + '/other/token', timeout=2)


if __name__ == '__main__':
    unittest.main()
