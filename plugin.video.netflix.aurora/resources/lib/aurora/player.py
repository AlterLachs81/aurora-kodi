# -*- coding: utf-8 -*-
"""Kodi InputStream Adaptive hand-off for a resolved DASH resource.

This module deliberately starts at the Kodi boundary. Aurora still needs its
own Netflix MSL manifest and license adapter before it can provide a resource
to these functions.
"""
from urllib.parse import urlencode, urlsplit

import xbmcplugin


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
