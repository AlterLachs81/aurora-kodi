# -*- coding: utf-8 -*-
"""Aurora's first standalone Netflix MSL transport layer.

The wire format follows Netflix's Message Security Layer and is informed by
the MIT-licensed CastagnaIT Kodi add-on implementation. This module is Aurora
code; it does not import or call that add-on. Playback manifest construction
and license-response handling remain separate work.
"""
import base64
import gzip
import json
import os
import random
import time
from http.cookiejar import Cookie, CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

import xbmcvfs


try:
    from Cryptodome.Cipher import AES, PKCS1_OAEP
    from Cryptodome.Hash import HMAC, SHA256
    from Cryptodome.PublicKey import RSA
    from Cryptodome.Util import Padding
except ImportError:
    try:
        from Crypto.Cipher import AES, PKCS1_OAEP
        from Crypto.Hash import HMAC, SHA256
        from Crypto.PublicKey import RSA
        from Crypto.Util import Padding
    except ImportError:
        AES = PKCS1_OAEP = HMAC = SHA256 = RSA = Padding = None


MANIFEST_ENDPOINT = 'https://www.netflix.com/msl/playapi/cadmium/licensedmanifest/1'


class MSLRequestError(RuntimeError):
    """Netflix MSL rejected or could not process an Aurora request."""


def _state_path():
    import xbmcaddon
    profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
    return os.path.join(profile, 'msl_session.json')


def _cookie_jar(entries):
    jar = CookieJar()
    for entry in entries:
        domain = entry.get('domain') or ''
        name = entry.get('name')
        if not domain or not name:
            continue
        expires = int(entry.get('expires') or 0)
        jar.set_cookie(Cookie(
            version=0, name=name, value=entry.get('value', ''), port=None,
            port_specified=False, domain=domain, domain_specified=True,
            domain_initial_dot=domain.startswith('.'), path=entry.get('path') or '/',
            path_specified=True, secure=bool(entry.get('secure', True)),
            expires=expires or None, discard=not expires, comment=None,
            comment_url=None, rest={'HttpOnly': bool(entry.get('http_only', False))},
            rfc2109=False,
        ))
    return jar


class _MSLCrypto:
    """RSA key exchange and AES-CBC/HMAC operations for a desktop MSL session."""

    def __init__(self, saved=None):
        if RSA is None:
            raise MSLRequestError(
                'Aurora benötigt die Kodi-Abhängigkeit script.module.pycryptodome.'
            )
        saved = saved or {}
        try:
            self.rsa_key = RSA.import_key(saved['rsa_private_key'].encode('ascii'))
            self.encryption_key = base64.b64decode(saved['encryption_key'], validate=True)
            self.sign_key = base64.b64decode(saved['sign_key'], validate=True)
            self.mastertoken = saved['mastertoken']
            self.sequence_number = int(saved['sequence_number'])
            self.bound_esn = saved.get('bound_esn')
        except (KeyError, TypeError, ValueError):
            self.rsa_key = RSA.generate(2048)
            self.encryption_key = None
            self.sign_key = None
            self.mastertoken = None
            self.sequence_number = 0
            self.bound_esn = None

    def key_request_data(self):
        public_key = self.rsa_key.public_key().export_key(format='DER')
        return [{
            'scheme': 'ASYMMETRIC_WRAPPED',
            'keydata': {
                'publickey': base64.b64encode(public_key).decode('ascii'),
                'mechanism': 'JWK_RSA',
                'keypairid': 'rsaKeypairId',
            },
        }]

    def accept_key_response(self, response):
        key_data = response['keyresponsedata']
        rsa = PKCS1_OAEP.new(self.rsa_key)
        self.encryption_key = self._unwrap_key(rsa.decrypt(
            base64.b64decode(key_data['keydata']['encryptionkey'])))
        self.sign_key = self._unwrap_key(rsa.decrypt(
            base64.b64decode(key_data['keydata']['hmackey'])))
        self.mastertoken = key_data['mastertoken']
        token_data = json.loads(base64.b64decode(
            self.mastertoken['tokendata']).decode('utf-8'))
        self.sequence_number = int(token_data.get('sequencenumber', 0))

    @staticmethod
    def _unwrap_key(value):
        encoded = json.loads(value.decode('utf-8'))['k']
        encoded += '=' * ((4 - len(encoded) % 4) % 4)
        return base64.urlsafe_b64decode(encoded.encode('ascii'))

    def encrypt(self, value, esn):
        from secrets import token_bytes
        iv = token_bytes(16)
        cipher = AES.new(self.encryption_key, AES.MODE_CBC, iv)
        ciphertext = cipher.encrypt(Padding.pad(value.encode('utf-8'), AES.block_size))
        return json.dumps({
            'ciphertext': base64.b64encode(ciphertext).decode('ascii'),
            'keyid': '{}_{}'.format(esn, self.sequence_number),
            'sha256': 'AA==',
            'iv': base64.b64encode(iv).decode('ascii'),
        })

    def decrypt(self, envelope):
        value = json.loads(envelope)
        iv = base64.b64decode(value['iv'])
        ciphertext = base64.b64decode(value['ciphertext'])
        cipher = AES.new(self.encryption_key, AES.MODE_CBC, iv)
        return Padding.unpad(cipher.decrypt(ciphertext), AES.block_size)

    def sign(self, value):
        return base64.b64encode(
            HMAC.new(self.sign_key, value.encode('utf-8'), SHA256).digest()
        ).decode('ascii')

    def export(self, esn):
        return {
            'rsa_private_key': self.rsa_key.export_key().decode('ascii'),
            'encryption_key': base64.b64encode(self.encryption_key).decode('ascii'),
            'sign_key': base64.b64encode(self.sign_key).decode('ascii'),
            'mastertoken': self.mastertoken,
            'sequence_number': self.sequence_number,
            'bound_esn': esn,
        }


class MSLClient:
    """Send authenticated MSL requests using Aurora's imported Netflix cookies."""

    def __init__(self, cookies, esn, language='en-US', user_agent=None, client_info=None):
        self.cookies = list(cookies or [])
        self.esn = str(esn or '').strip()
        if not self.esn:
            raise MSLRequestError('Netflix lieferte keine Gerätekennung (ESN).')
        self.language = language or 'en-US'
        self.client_info = client_info or {}
        self.user_agent = user_agent or (
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        )
        self.opener = build_opener(HTTPCookieProcessor(_cookie_jar(self.cookies)))
        self.crypto = _MSLCrypto(self._load_state())

    def _load_state(self):
        path = _state_path()
        if not xbmcvfs.exists(path):
            return {}
        try:
            with xbmcvfs.File(path) as handle:
                value = json.loads(handle.read())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self):
        path = _state_path()
        xbmcvfs.mkdirs(os.path.dirname(path))
        with xbmcvfs.File(path, 'w') as handle:
            handle.write(json.dumps(self.crypto.export(self.esn), separators=(',', ':')))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _post(self, url, body):
        request = Request(url, data=body.encode('utf-8'), headers={
            'User-Agent': self.user_agent,
            'Content-Type': 'text/plain',
            'Accept': '*/*',
        }, method='POST')
        try:
            with self.opener.open(request, timeout=25) as response:
                return response.read().decode('utf-8', errors='replace')
        except HTTPError as exc:
            raise MSLRequestError('Netflix-MSL antwortete mit HTTP {}.'.format(exc.code)) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise MSLRequestError('Netflix-MSL ist nicht erreichbar: {}'.format(exc)) from exc

    def perform_key_handshake(self):
        """Negotiate an MSL master token and symmetric keys with Netflix."""
        message_id = random.SystemRandom().randint(0, 2 ** 52)
        header_data = json.dumps({
            'messageid': message_id,
            'renewable': True,
            'capabilities': {'languages': [self.language], 'compressionalgos': []},
            'keyrequestdata': self.crypto.key_request_data(),
        })
        header = {
            'entityauthdata': {'scheme': 'NONE', 'authdata': {'identity': self.esn}},
            'headerdata': base64.b64encode(header_data.encode('utf-8')).decode('ascii'),
            'signature': '',
        }
        payload = json.dumps({
            'messageid': message_id, 'data': '', 'sequencenumber': 1, 'endofmsg': True,
        })
        body = json.dumps(header, sort_keys=True) + json.dumps({
            'payload': base64.b64encode(payload.encode('utf-8')).decode('ascii'),
            'signature': '',
        })
        response = self._post(MANIFEST_ENDPOINT, body)
        messages = _json_messages(response)
        if not messages or 'headerdata' not in messages[0]:
            raise MSLRequestError('Netflix-MSL lieferte keine Antwort auf den Schlüsselaustausch.')
        handshake_header = _decode_base64_json(messages[0]['headerdata'])
        _raise_msl_error(handshake_header)
        try:
            self.crypto.accept_key_response(handshake_header)
        except (KeyError, TypeError, ValueError) as exc:
            raise MSLRequestError('Netflix-MSL-Antwort enthält keine gültigen Sitzungsschlüssel.') from exc
        self.crypto.bound_esn = self.esn
        self._save_state()
        return True

    def licensed_manifest(self, video_id, profiles, challenge, session_id, xid=None):
        """Request a Netflix v2 licensed manifest for one viewable ID."""
        xid = xid or str(time.time_ns())[:18]
        data = manifest_request_data(
            video_id, profiles, challenge, session_id,
            language=self.language, xid=xid, client_info=self.client_info,
        )
        return self.request(manifest_endpoint(self.client_info), data), xid

    def request(self, endpoint, request_data):
        """Send one MSL request and return its decoded JSON response."""
        if (not self.crypto.mastertoken or not self.crypto.encryption_key or
                self.crypto.bound_esn != self.esn or self._mastertoken_expired()):
            self.perform_key_handshake()
        cookie_values = {cookie.get('name'): cookie.get('value') for cookie in self.cookies}
        netflix_id = cookie_values.get('NetflixId')
        secure_id = cookie_values.get('SecureNetflixId')
        if not netflix_id or not secure_id:
            raise MSLRequestError('Die Netflix-Sitzung enthält nicht beide Anmelde-Cookies.')

        message_id = random.SystemRandom().randint(0, 2 ** 52)
        header_data = json.dumps({
            'messageid': message_id,
            'renewable': True,
            'capabilities': {'languages': [self.language], 'compressionalgos': ['GZIP']},
            'sender': self.esn,
            'userauthdata': {
                'scheme': 'NETFLIXID',
                'authdata': {'netflixid': netflix_id, 'securenetflixid': secure_id},
            },
        })
        header_envelope = self.crypto.encrypt(header_data, self.esn)
        header = {
            'headerdata': base64.b64encode(header_envelope.encode('utf-8')).decode('ascii'),
            'signature': self.crypto.sign(header_envelope),
            'mastertoken': self.crypto.mastertoken,
        }
        data = base64.b64encode(json.dumps(request_data).encode('utf-8')).decode('ascii')
        chunk_data = json.dumps({
            'messageid': message_id, 'data': data, 'sequencenumber': 1, 'endofmsg': True,
        })
        chunk_envelope = self.crypto.encrypt(chunk_data, self.esn)
        body = json.dumps(header) + json.dumps({
            'payload': base64.b64encode(chunk_envelope.encode('utf-8')).decode('ascii'),
            'signature': self.crypto.sign(chunk_envelope),
        })
        response = self._post(endpoint, body)
        return self._decode_response(response)

    def _mastertoken_expired(self):
        try:
            token_data = _decode_base64_json(self.crypto.mastertoken['tokendata'])
            return float(token_data['expiration']) <= time.time()
        except (KeyError, TypeError, ValueError):
            return True

    def _decode_response(self, response):
        messages = _json_messages(response)
        if not messages or 'headerdata' not in messages[0]:
            raise MSLRequestError('Netflix-MSL lieferte keine gültige Antwort.')
        header_envelope = _decode_base64_json(messages[0]['headerdata'])
        try:
            response_header = json.loads(self.crypto.decrypt(json.dumps(header_envelope)).decode('utf-8'))
        except (KeyError, TypeError, ValueError) as exc:
            raise MSLRequestError('Netflix-MSL-Kopf konnte nicht entschlüsselt werden.') from exc
        _raise_msl_error(response_header)

        parts = []
        for message in messages:
            payload = message.get('payload')
            if not payload:
                continue
            try:
                envelope = _decode_base64_json(payload)
                plaintext = json.loads(self.crypto.decrypt(json.dumps(envelope)).decode('utf-8'))
                encoded_data = plaintext.get('data')
                if not encoded_data:
                    continue
                chunk = base64.b64decode(encoded_data)
                if plaintext.get('compressionalgo') == 'GZIP':
                    chunk = gzip.decompress(chunk)
                else:
                    chunk = chunk.decode('utf-8')
                parts.append(chunk.decode('utf-8') if isinstance(chunk, bytes) else chunk)
            except (KeyError, TypeError, ValueError, OSError) as exc:
                raise MSLRequestError('Netflix-MSL-Nutzdaten konnten nicht entschlüsselt werden.') from exc
        if not parts:
            raise MSLRequestError('Netflix-MSL lieferte keine entschlüsselten Nutzdaten.')
        try:
            result = json.loads(''.join(parts))
        except ValueError as exc:
            raise MSLRequestError('Netflix-MSL-Nutzdaten sind kein gültiges JSON.') from exc
        _raise_msl_error(result)
        self._save_state()
        return result


def manifest_endpoint(client_info, request_name='prefetch/licensedManifest'):
    """Build the current Netflix licensed-manifest MSL endpoint URL."""
    required = ('build_identifier', 'browser_info_version', 'os_name', 'os_version')
    if not isinstance(client_info, dict) or any(not client_info.get(key) for key in required):
        raise MSLRequestError('Netflix lieferte unvollständige Browserdaten für MSL.')
    params = [
        ('reqAttempt', ''),
        ('reqName', request_name),
        ('clienttype', 'akira'),
        ('uiversion', str(client_info['build_identifier'])),
        ('browsername', 'chrome'),
        ('browserversion', str(client_info['browser_info_version']).lower()),
        ('osname', str(client_info['os_name']).lower()),
        ('osversion', str(client_info['os_version'])),
    ]
    return MANIFEST_ENDPOINT + '?' + urlencode(params)


def manifest_request_data(video_id, profiles, challenge, session_id, language='en-US', xid=None,
                          client_info=None):
    """Build the basic Netflix licensed-manifest request envelope."""
    client_info = client_info or {}
    required = ('ui_version', 'client_version', 'browser_info_version', 'os_name', 'os_version')
    if any(not client_info.get(key) for key in required):
        raise MSLRequestError('Netflix lieferte unvollständige Playerdaten für die MSL-Manifestabfrage.')
    now = int(time.time())
    xid = xid or str(time.time_ns())[:18]
    params = {
        'type': 'standard',
        'manifestVersion': 'v2',
        'viewableId': str(video_id),
        'profiles': list(profiles),
        'flavor': 'PRE_FETCH',
        'drmType': 'widevine',
        'drmVersion': 25,
        'usePsshBox': True,
        'isBranching': False,
        'useHttpsStreams': True,
        'imageSubtitleHeight': 1080,
        'uiVersion': client_info['ui_version'],
        'uiPlatform': 'SHAKTI',
        'clientVersion': client_info['client_version'],
        'platform': client_info['browser_info_version'],
        'osVersion': client_info['os_version'],
        'osName': client_info['os_name'],
        'supportsPreReleasePin': True,
        'supportsWatermark': True,
        'supportsUnequalizedDownloadables': True,
        'showAllSubDubTracks': False,
        'titleSpecificData': {str(video_id): {'unletterboxed': True}},
        'videoOutputInfo': [{
            'type': 'DigitalVideoOutputDescriptor',
            'outputType': 'unknown',
            'supportedHdcpVersions': [],
            'isHdcpEngaged': False,
        }],
        'preferAssistiveAudio': False,
        'isUIAutoPlay': False,
        'isNonMember': False,
        'desiredVmaf': 'plus_lts',
        'desiredSegmentVmaf': 'plus_lts',
        'requestSegmentVmaf': False,
        'supportsPartialHydration': False,
        'contentPlaygraph': ['start'],
        'supportsAdBreakHydration': False,
        'liveMetadataFormat': 'INDEXED_SEGMENT_TEMPLATE',
        'useBetterTextUrls': True,
        'profileGroups': [{'name': 'default', 'profiles': list(profiles)}],
        'challenge': challenge,
        'challenges': {'default': [{
            'drmSessionId': session_id or 'session',
            'clientTime': now,
            'challengeBase64': challenge,
            'xid': xid,
        }]},
        'licenseType': 'standard',
    }
    return {
        'version': 2,
        'url': 'licensedManifest',
        'id': int(time.time() * 100000000),
        'languages': [language],
        'params': params,
        'echo': '',
    }


def _json_messages(source):
    decoder = json.JSONDecoder()
    values = []
    offset = 0
    while offset < len(source):
        while offset < len(source) and source[offset].isspace():
            offset += 1
        if offset == len(source):
            break
        value, offset = decoder.raw_decode(source, offset)
        if not isinstance(value, dict):
            raise MSLRequestError('Netflix-MSL-Nachricht hat ein ungültiges Format.')
        values.append(value)
    return values


def _decode_base64_json(value):
    return json.loads(base64.b64decode(value).decode('utf-8'))


def _raise_msl_error(data):
    if not isinstance(data, dict):
        return
    if data.get('error'):
        detail = data['error']
        message = detail.get('errorDisplayMessage') if isinstance(detail, dict) else None
        raise MSLRequestError(message or 'Netflix hat die MSL-Anfrage abgelehnt.')
    encoded = data.get('errordata')
    if encoded:
        try:
            detail = json.loads(base64.b64decode(encoded).decode('utf-8'))
        except (ValueError, TypeError):
            detail = {}
        raise MSLRequestError(detail.get('errormsg') or 'Netflix hat die MSL-Anfrage abgelehnt.')
