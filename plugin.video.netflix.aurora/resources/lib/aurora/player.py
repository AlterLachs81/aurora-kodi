# -*- coding: utf-8 -*-
"""Kodi InputStream Adaptive hand-off for a resolved DASH resource.

This module deliberately starts at the Kodi boundary. Aurora still needs its
own Netflix MSL manifest and license adapter before it can provide a resource
to these functions.
"""
from urllib.parse import urlencode, urlsplit

import xbmcplugin
import xbmcgui

from resources.lib.aurora.playback_state import create as create_playback_state


SERVICE_PORT = 8765
PSSH_KID = (
    'AAAANHBzc2gAAAAA7e+LqXnWSs6jyCfc1R0h7QAAABQIARIQAAAAAAPSZ0kAAAAAAAAAAA=='
    '|AAAAAAPSZ0kAAAAAAAAAAA=='
)
WIDEVINE_SERVER_CERTIFICATE = (
    'Cr0CCAMSEOVEukALwQ8307Y2+LVP+0MYh/HPkwUijgIwggEKAoIBAQDm875btoWUbGqQD8eA'
    'GuBlGY+Pxo8YF1LQR+Ex0pDONMet8EHslcZRBKNQ/09RZFTP0vrYimyYiBmk9GG+S0wB3CRI'
    'TgweNE15cD33MQYyS3zpBd4z+sCJam2+jj1ZA4uijE2dxGC+gRBRnw9WoPyw7D8RuhGSJ95O'
    'Etzg3Ho+mEsxuE5xg9LM4+Zuro/9msz2bFgJUjQUVHo5j+k4qLWu4ObugFmc9DLIAohL58UR'
    '5k0XnvizulOHbMMxdzna9lwTw/4SALadEV/CZXBmswUtBgATDKNqjXwokohncpdsWSauH6vf'
    'S6FXwizQoZJ9TdjSGC60rUB2t+aYDm74cIuxAgMBAAE6EHRlc3QubmV0ZmxpeC5jb20SgAOE'
    '0y8yWw2Win6M2/bw7+aqVuQPwzS/YG5ySYvwCGQd0Dltr3hpik98WijUODUr6PxMn1ZYXOLo'
    '3eED6xYGM7Riza8XskRdCfF8xjj7L7/THPbixyn4mULsttSmWFhexzXnSeKqQHuoKmerqu0n'
    'u39iW3pcxDV/K7E6aaSr5ID0SCi7KRcL9BCUCz1g9c43sNj46BhMCWJSm0mx1XFDcoKZWhpj'
    '5FAgU4Q4e6f+S8eX39nf6D6SJRb4ap7Znzn7preIvmS93xWjm75I6UBVQGo6pn4qWNCgLYlG'
    'GCQCUm5tg566j+/g5jvYZkTJvbiZFwtjMW5njbSRwB3W4CrKoyxw4qsJNSaZRTKAvSjTKdqV'
    'DXV/U5HK7SaBA6iJ981/aforXbd2vZlRXO/2S+Maa2mHULzsD+S5l4/YGpSt7PnkCe25F+nA'
    'ovtl/ogZgjMeEdFyd/9YMYjOS4krYmwp3yJ7m9ZzYCQ6I8RQN4x/yLlHG5RH/+WNLNUs6JAZ'
    '0fFdCmw='
)


class PlaybackError(ValueError):
    """A resolved stream cannot be handed safely to Kodi."""


def _check_http_url(value, field):
    value = str(value or '').strip()
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise PlaybackError('{} muss eine HTTP(S)-Adresse ohne Zugangsdaten sein.'.format(field))
    return value


def prepare_dash_item(item, manifest_url, license_url, license_headers=None,
                      license_challenge='R{SSM}!b{SID}', title='', art='', plot=''):
    """Configure a Kodi ListItem for a DASH stream and a Widevine license URL.

    ``license_challenge`` uses InputStream Adaptive's request-template syntax.
    Callers must supply the endpoint that knows how to turn that challenge into
    a valid license response; this function does not implement Netflix MSL.
    """
    manifest_url = _check_http_url(manifest_url, 'MPD-Manifest')
    license_url = _check_http_url(license_url, 'Widevine-Lizenzserver')
    headers = license_headers or {}
    if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                           for k, v in headers.items()):
        raise PlaybackError('Lizenz-Header müssen Schlüssel und Textwerte enthalten.')
    if not isinstance(license_challenge, str) or not license_challenge:
        raise PlaybackError('Die Lizenz-Challenge-Vorlage fehlt.')

    item.setPath(manifest_url)
    item.setMimeType('application/dash+xml')
    item.setContentLookup(False)
    item.setProperty('IsPlayable', 'true')
    item.setProperty('inputstream', 'inputstream.adaptive')
    item.setProperty('inputstream.adaptive.manifest_type', 'mpd')
    item.setProperty('inputstream.adaptive.license_type', 'com.widevine.alpha')
    item.setProperty(
        'inputstream.adaptive.license_key',
        '{}|{}||'.format(license_url, urlencode(headers)) if not license_challenge else
        '{}|{}|{}|'.format(license_url, urlencode(headers), license_challenge),
    )
    if title:
        item.setInfo('video', {'title': title, 'plot': plot or ''})
    if art:
        item.setArt({'thumb': art, 'poster': art, 'icon': art})
    return item


def resolve_dash(handle, item, manifest_url, license_url, license_headers=None,
                 license_challenge='R{SSM}!b{SID}', title='', art='', plot=''):
    """Resolve a Kodi plugin item after its playback resource has been obtained."""
    item = prepare_dash_item(
        item, manifest_url, license_url, license_headers, license_challenge,
        title, art, plot,
    )
    xbmcplugin.setResolvedUrl(handle, True, item)


def resolve_netflix(handle, entry, service_port=SERVICE_PORT):
    """Hand a title to Aurora's local MSL service and Kodi's Widevine player."""
    from secrets import token_urlsafe

    token = token_urlsafe(24)
    create_playback_state(token, entry)
    service_url = 'http://127.0.0.1:{}/aurora'.format(int(service_port))
    manifest_url = '{}/manifest/{}'.format(service_url, token)
    license_url = '{}/license/{}'.format(service_url, token)
    item = xbmcgui.ListItem(path=manifest_url, offscreen=True)
    item.setContentLookup(False)
    item.setMimeType('application/xml+dash')
    item.setInfo('video', {'title': entry.get('label') or '', 'plot': entry.get('plot') or ''})
    if entry.get('image'):
        item.setArt({'thumb': entry['image'], 'poster': entry['image'], 'icon': entry['image']})
    item.setProperty('IsPlayable', 'true')
    item.setProperty('ForceResolvePlugin', 'true')
    item.setProperty('inputstream', 'inputstream.adaptive')
    item.setProperty('inputstream.adaptive.manifest_type', 'mpd')
    item.setProperty('inputstream.adaptive.license_type', 'com.widevine.alpha')
    item.setProperty(
        'inputstream.adaptive.license_key',
        '{}||b{{SSM}}!b{{SID}}|'.format(license_url),
    )
    item.setProperty('inputstream.adaptive.server_certificate', WIDEVINE_SERVER_CERTIFICATE)
    item.setProperty('inputstream.adaptive.pre_init_data', PSSH_KID)
    item.setProperty(
        'inputstream.adaptive.stream_headers',
        'user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    )
    xbmcplugin.setResolvedUrl(handle, True, item)
