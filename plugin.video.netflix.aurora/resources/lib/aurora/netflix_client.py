# -*- coding: utf-8 -*-
"""Aurora's direct HTTPS client for Netflix web endpoints."""
from http.cookiejar import Cookie, CookieJar
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from resources.lib.aurora.session import load_cookies


class NetflixConnectionError(RuntimeError):
    """The Netflix service could not be reached or the session was rejected."""


def _cookie_jar(entries):
    jar = CookieJar()
    for entry in entries:
        domain = entry.get('domain') or ''
        name = entry.get('name')
        if not domain or not name:
            continue
        expires = int(entry.get('expires') or 0)
        cookie = Cookie(
            version=0,
            name=name,
            value=entry.get('value', ''),
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=True,
            domain_initial_dot=domain.startswith('.'),
            path=entry.get('path') or '/',
            path_specified=True,
            secure=bool(entry.get('secure', True)),
            expires=expires or None,
            discard=not expires,
            comment=None,
            comment_url=None,
            rest={'HttpOnly': bool(entry.get('http_only', False))},
            rfc2109=False,
        )
        jar.set_cookie(cookie)
    return jar


class NetflixClient:
    """Use Aurora's own stored browser session without invoking another add-on."""

    def __init__(self, cookies=None):
        self.cookies = load_cookies() if cookies is None else cookies
        if not self.cookies:
            raise NetflixConnectionError('Es ist noch keine Netflix-Sitzung importiert.')
        self.opener = build_opener(HTTPCookieProcessor(_cookie_jar(self.cookies)))
        self.api_url = None
        self.auth_url = None
        self.user_guid = None

    def check_session(self):
        try:
            body, response_url = self._get('https://www.netflix.com/browse')
            final = urlparse(response_url)
            if final.hostname not in ('netflix.com', 'www.netflix.com'):
                raise NetflixConnectionError('Netflix hat auf eine unerwartete Adresse umgeleitet.')
            if '/login' in final.path.lower():
                raise NetflixConnectionError('Netflix hat die importierte Sitzung abgelehnt.')
            react_context = _extract_react_context(body)
            self._read_session_context(react_context)
            if self.api_url is None or self.auth_url is None:
                raise NetflixConnectionError('Netflix hat keine gültigen Sitzungsdaten geliefert.')
            return True
        except NetflixConnectionError:
            raise
        except HTTPError as exc:
            raise NetflixConnectionError('Netflix antwortete mit HTTP {}.'.format(exc.code)) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise NetflixConnectionError('Netflix ist nicht erreichbar: {}'.format(exc)) from exc

    def _get(self, url):
        request = Request(url, headers=_browser_headers())
        with self.opener.open(request, timeout=25) as response:
            return response.read(), response.geturl()

    def _read_session_context(self, react_context):
        user = _value_at(react_context, ('models', 'userInfo', 'data'))
        status = _unwrap(user.get('membershipStatus')) if isinstance(user, dict) else None
        if status != 'CURRENT_MEMBER':
            raise NetflixConnectionError('Netflix meldet keine aktive Mitgliedschaft für diese Sitzung.')
        self.auth_url = _unwrap(user.get('authURL'))
        self.user_guid = _unwrap(user.get('userGuid'))
        member_api = _unwrap(_value_at(react_context, ('models', 'services', 'data', 'memberapi')))
        if isinstance(member_api, dict):
            protocol = member_api.get('protocol', 'https')
            hostname = member_api.get('hostname')
            paths = member_api.get('path') or []
            if hostname and paths:
                self.api_url = '{}://{}{}'.format(protocol, hostname, paths[0].rstrip('/'))
        elif isinstance(member_api, str):
            self.api_url = member_api.rstrip('/')

    def path_request(self, paths):
        """Request JSON Graph paths from the Netflix member API."""
        if not self.api_url or not self.auth_url:
            self.check_session()
        endpoint = self.api_url + '/pathEvaluator'
        params = {
            'drmSystem': 'widevine',
            'falcor_server': '0.1.0',
            'withSize': 'false',
            'materialize': 'false',
            'routeAPIRequestsThroughFTL': 'false',
            'isVolatileBillboardsEnabled': 'true',
            'isTop10Supported': 'true',
            'original_path': '/shakti/mre/pathEvaluator',
        }
        form = [('path', json.dumps(path, separators=(',', ':'))) for path in paths]
        form.append(('authURL', self.auth_url))
        headers = _browser_headers()
        headers.update({
            'Accept': 'application/json, text/javascript, */*',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://www.netflix.com',
            'Referer': 'https://www.netflix.com/browse',
            'x-netflix.nq.stack': 'prod',
        })
        if self.user_guid:
            headers['x-netflix.request.client.user.guid'] = self.user_guid
        request = Request(
            endpoint + '?' + urlencode(params),
            data=urlencode(form).encode('utf-8'),
            headers=headers,
            method='POST',
        )
        try:
            with self.opener.open(request, timeout=25) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise NetflixConnectionError('Netflix-Katalogabfrage fehlgeschlagen: {}'.format(exc)) from exc
        if payload.get('status') == 'error':
            raise NetflixConnectionError(payload.get('message') or 'Netflix hat die Abfrage abgelehnt.')
        graph = payload.get('jsonGraph')
        if not isinstance(graph, dict):
            raise NetflixConnectionError('Netflix lieferte keine Katalogdaten.')
        return graph


def _browser_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept-Language': 'de-DE,de;q=0.9,en;q=0.7',
    }


def _extract_react_context(content):
    text = content.decode('utf-8', errors='replace') if isinstance(content, bytes) else content
    match = re.search(r'netflix\.reactContext\s*=\s*(\{.*?\});\s*</script>', text, re.DOTALL)
    if not match:
        raise NetflixConnectionError('Netflix-Seitenstruktur nicht erkannt; Sitzungsdaten fehlen.')
    try:
        return json.loads(match.group(1))
    except ValueError as exc:
        raise NetflixConnectionError('Netflix-Seitendaten konnten nicht gelesen werden.') from exc


def _value_at(data, path):
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if isinstance(current, dict) and current.get('$type') == 'atom':
            current = current.get('value')
    return _unwrap(current)


def _unwrap(value):
    if isinstance(value, dict) and value.get('$type') == 'atom':
        return value.get('value')
    return value
