import base64
import json
import sys
import types
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / 'plugin.video.netflix.aurora'
sys.path.insert(0, str(PLUGIN))
sys.modules.setdefault('xbmcvfs', types.ModuleType('xbmcvfs'))

from resources.lib.aurora.msl import (  # noqa: E402
    MSLClient, MSLRequestError, _json_messages, manifest_endpoint, manifest_request_data,
)


CLIENT_INFO = {
    'build_identifier': 'build-1',
    'ui_version': 'ui-1',
    'client_version': '6.1.2',
    'browser_info_version': '131.0.0.0',
    'os_name': 'linux',
    'os_version': 'LibreELEC',
}


class FakeCrypto:
    def decrypt(self, envelope):
        label = json.loads(envelope)['label']
        if label == 'header':
            return b'{"messageid":1}'
        body = json.dumps({
            'data': base64.b64encode(b'{"result":{"ok":true}}').decode('ascii'),
        })
        return body.encode('utf-8')


class MSLTransportTests(unittest.TestCase):
    def test_json_messages_parse_concatenated_msl_objects(self):
        source = '{"one":1}{"two":2}'
        self.assertEqual(_json_messages(source), [{'one': 1}, {'two': 2}])

    def test_json_messages_reject_invalid_payload(self):
        with self.assertRaises((ValueError, MSLRequestError)):
            _json_messages('{bad}')

    def test_manifest_request_has_linux_xid_and_client_metadata(self):
        data = manifest_request_data(
            '1234', ['profile-1'], 'Y2hhbGxlbmdl', 'session-1',
            language='de-DE', xid='170000000000000000', client_info=CLIENT_INFO,
        )
        params = data['params']
        self.assertEqual(data['languages'], ['de-DE'])
        self.assertEqual(params['clientVersion'], '6.1.2')
        self.assertEqual(params['challenges']['default'][0]['xid'], '170000000000000000')
        self.assertNotIn('xid', params)

    def test_manifest_endpoint_uses_observed_client_metadata(self):
        url = manifest_endpoint(CLIENT_INFO)
        self.assertIn('uiversion=build-1', url)
        self.assertIn('browserversion=131.0.0.0', url)
        self.assertIn('osname=linux', url)

    def test_encrypted_response_envelope_is_decoded(self):
        client = MSLClient.__new__(MSLClient)
        client.crypto = FakeCrypto()
        client._save_state = lambda: None
        header = base64.b64encode(b'{"label":"header"}').decode('ascii')
        payload = base64.b64encode(b'{"label":"payload"}').decode('ascii')
        response = json.dumps({'headerdata': header}) + json.dumps({'payload': payload})
        self.assertEqual(client._decode_response(response), {'ok': True})


if __name__ == '__main__':
    unittest.main()
