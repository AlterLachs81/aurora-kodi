# -*- coding: utf-8 -*-
"""Small, independent reader for Netflix's JSON Graph catalogue responses."""
from resources.lib.aurora.netflix_client import NetflixClient


_VIDEO_FIELDS = [
    'id', 'summary', 'title', 'synopsis', 'releaseYear', 'runtime',
    'boxarts', 'interestingMoment', 'availability', 'delivery',
]


def home_sections(client=None):
    client = client or NetflixClient()
    paths = [
        ['loco', 'componentSummary'],
        ['loco', {'from': 0, 'to': 50}, 'componentSummary'],
        ['loco', {'from': 0, 'to': 50}, {'from': 0, 'to': 3}, 'reference', ['title', 'summary']],
    ]
    graph = client.path_request(paths)
    result = []
    for list_id, node in (graph.get('lists') or {}).items():
        summary = _unwrap((node.get('componentSummary') or {}).get('value'))
        if not isinstance(summary, dict):
            continue
        context = summary.get('context')
        title = summary.get('displayName') or context
        if context and title:
            result.append({'id': str(list_id), 'context': str(context), 'title': str(title)})
    return result


def videos(list_id, client=None, start=0, count=40):
    client = client or NetflixClient()
    end = max(int(start), 0) + min(max(int(count), 1), 40) - 1
    graph = client.path_request([
        ['lists', str(list_id), {'from': max(int(start), 0), 'to': end}, 'reference', _VIDEO_FIELDS],
        ['lists', str(list_id), 'componentSummary'],
    ])
    list_node = (graph.get('lists') or {}).get(str(list_id)) or {}
    return _entries_from_list(graph, list_node)


def search(term, client=None, start=0, count=40):
    client = client or NetflixClient()
    term = str(term).strip()
    if not term:
        return []
    start = max(int(start), 0)
    end = start + min(max(int(count), 1), 40) - 1
    base = ['search', 'byTerm', '|' + term, 'titles', 47]
    graph = client.path_request([
        base + [['id', 'name', 'requestId', 'trackIds']],
        base + [{'from': start, 'to': end}, 'reference', _VIDEO_FIELDS],
    ])
    search_data = graph.get('search') or {}
    references = search_data.get('byReference') or {}
    if not references:
        return []
    first_list = next(iter(references.values()))
    return _entries_from_list(graph, first_list)


def seasons(show_id, client=None):
    client = client or NetflixClient()
    show_id = str(show_id)
    graph = client.path_request([
        ['videos', show_id, 'title'],
        ['videos', show_id, 'seasonList', {'from': 0, 'to': 49}, 'reference',
         ['summary', 'title', 'boxarts']],
        ['videos', show_id, 'seasonList', 'componentSummary'],
    ])
    show = (graph.get('videos') or {}).get(show_id) or {}
    season_list = show.get('seasonList') or {}
    result = []
    for _, reference in sorted(
        ((int(key), value) for key, value in season_list.items() if str(key).isdigit()),
        key=lambda pair: pair[0],
    ):
        target = _reference_path(reference)
        if not target:
            continue
        season = _at(graph, target)
        if not isinstance(season, dict):
            continue
        summary = _unwrap(season.get('summary')) or {}
        if not isinstance(summary, dict):
            summary = {}
        title = _unwrap(season.get('title')) or summary.get('shortName') or summary.get('title')
        if title:
            result.append({
                'id': str(target[-1]),
                'title': str(title),
                'image': _at(season, ['boxarts', '_342x684', 'jpg', 'value']) or '',
                'type': 'season',
            })
    return result


def episodes(season_id, client=None, start=0, count=40):
    client = client or NetflixClient()
    season_id = str(season_id)
    start = max(int(start), 0)
    end = start + min(max(int(count), 1), 40) - 1
    graph = client.path_request([
        ['seasons', season_id, 'episodes', {'from': start, 'to': end}, 'reference', _VIDEO_FIELDS],
        ['seasons', season_id, 'episodes', 'componentSummary'],
    ])
    season = (graph.get('seasons') or {}).get(season_id) or {}
    return _entries_from_list(graph, season.get('episodes') or {})


def _entries_from_list(graph, list_node):
    refs = []
    for key, value in list_node.items():
        if str(key).isdigit():
            refs.append((int(key), value))
    entries = []
    for index, reference in sorted(refs):
        target = _reference_path(reference)
        if not target:
            continue
        video = _at(graph, target)
        if not isinstance(video, dict):
            continue
        entry = _video_entry(video, target)
        if entry:
            entries.append(entry)
    return entries


def _video_entry(video, target):
    summary = _unwrap(video.get('summary')) or {}
    if not isinstance(summary, dict):
        summary = {}
    title = _unwrap(video.get('title')) or summary.get('title')
    if isinstance(title, dict):
        title = title.get('value')
    if not title:
        return None
    image = (
        _at(video, ['boxarts', '_342x684', 'jpg', 'value']) or
        _at(video, ['boxarts', '_665x375', 'jpg', 'value']) or
        _at(video, ['interestingMoment', '_665x375', 'jpg', 'value'])
    )
    year = _unwrap(video.get('releaseYear')) or summary.get('year')
    runtime = _unwrap(video.get('runtime')) or 0
    synopsis = _unwrap(video.get('synopsis')) or summary.get('synopsis') or ''
    return {
        'id': str(target[-1]),
        'title': str(title),
        'image': str(image or ''),
        'year': year or '',
        'runtime': runtime or 0,
        'plot': str(synopsis),
        'type': _media_type(video, summary),
    }


def _media_type(video, summary):
    for source in (video.get('delivery'), video.get('availability'), video.get('summary')):
        value = _unwrap(source)
        if isinstance(value, dict):
            kind = value.get('type') or value.get('videoType')
            if kind:
                return str(kind).lower()
    return str(summary.get('type') or '').lower()


def _reference_path(value):
    if isinstance(value, dict) and 'reference' in value:
        value = value['reference']
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and value.get('$type') == 'ref':
        return value.get('value')
    return None


def _at(data, path):
    value = data
    for key in path:
        value = _unwrap(value)
        if not isinstance(value, dict):
            return None
        value = value.get(str(key), value.get(key))
    value = _unwrap(value)
    return value


def _unwrap(value):
    if isinstance(value, dict):
        if value.get('$type') == 'atom':
            return value.get('value')
        if value.get('$type') == 'ref':
            return value.get('value')
        if 'value' in value and len(value) == 1:
            return value['value']
    return value
