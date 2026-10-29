# -*- coding: utf-8 -*-
"""Import a Netflix browser session from an NFAuthentication.key file.

The key format is produced by the NFAuthenticationKey desktop helper. This
module is Aurora's own importer; it does not call or depend on another Kodi
add-on.
"""
import base64
import json
import time


class AuthenticationKeyError(ValueError):
    """The selected key is invalid, expired, or cannot be decrypted."""


def _aes_module():
    try:
        from Cryptodome.Cipher import AES
        from Cryptodome.Util.Padding import unpad
    except ImportError:
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import unpad
        except ImportError as exc:
            raise AuthenticationKeyError(
                'Kodi benötigt die Python-Bibliothek PyCryptodome für den Schlüssel.'
            ) from exc
    return AES, unpad


def _decode_document(contents, pin):
    if not pin or not pin.isdigit():
        raise AuthenticationKeyError('Die PIN muss aus Ziffern bestehen.')
    try:
        AES, unpad = _aes_module()
        encrypted = base64.b64decode(contents.strip(), validate=True)
        if len(encrypted) <= AES.block_size or len(encrypted) % AES.block_size:
            raise ValueError('invalid encrypted length')
        key = (pin * 4).encode('utf-8')
        if len(key) != 16:
            raise ValueError('invalid PIN length')
        clear = AES.new(key, AES.MODE_CBC, iv=b'\x00' * AES.block_size).decrypt(encrypted)
        document = json.loads(unpad(clear, AES.block_size).decode('utf-8'))
    except AuthenticationKeyError:
        raise
    except Exception as exc:
        raise AuthenticationKeyError('Datei oder PIN ist ungültig.') from exc
    return document


def decode_authentication_key(contents, pin):
    """Return validated Netflix cookies from an NFAuthentication.key file."""
    document = _decode_document(contents, pin)
    expected = {
        'app_name': 'NFAuthenticationKey',
        'app_author': 'CastagnaIT',
    }
    if any(document.get(key) != value for key, value in expected.items()):
        raise AuthenticationKeyError('Dieses Format wird nicht unterstützt.')
    if document.get('app_system') not in ('Windows', 'Linux', 'MacOS'):
        raise AuthenticationKeyError('Dieses Format wird nicht unterstützt.')
    if not isinstance(document.get('timestamp'), (int, float)) or document['timestamp'] <= time.time():
        raise AuthenticationKeyError('Der Authentifizierungsschlüssel ist abgelaufen.')

    data = document.get('data') or {}
    source_cookies = data.get('cookies') if isinstance(data, dict) else None
    if not isinstance(source_cookies, list):
        raise AuthenticationKeyError('Die Datei enthält keine Browser-Cookies.')

    cookies = []
    for cookie in source_cookies:
        if not isinstance(cookie, dict):
            continue
        domain = str(cookie.get('domain') or '').lower()
        normalized_domain = domain.lstrip('.')
        if not (normalized_domain == 'netflix.com' or normalized_domain.endswith('.netflix.com')):
            continue
        name = cookie.get('name')
        value = cookie.get('value')
        if not name or value is None:
            continue
        expires = cookie.get('expirationDate', cookie.get('expires', 0))
        try:
            expires = int(float(expires or 0))
        except (TypeError, ValueError):
            expires = 0
        if expires > 0 and expires <= time.time():
            continue
        cookies.append({
            'name': str(name),
            'value': str(value),
            'domain': domain,
            'path': str(cookie.get('path') or '/'),
            'secure': bool(cookie.get('secure', True)),
            'expires': max(0, expires),
            'http_only': bool(cookie.get('httpOnly', False)),
        })

    if not cookies:
        raise AuthenticationKeyError('Die Datei enthält keine gültigen Netflix-Cookies.')
    return cookies
