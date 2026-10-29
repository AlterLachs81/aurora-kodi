# -*- coding: utf-8 -*-
"""Convert a resolved single-period VOD manifest into a DASH MPD.

This converts stream metadata only. It does not request a Netflix manifest,
create a Widevine challenge, or obtain a license.
"""
import base64
import uuid
import xml.etree.ElementTree as ET


MPD_NS = 'urn:mpeg:dash:schema:mpd:2011'
CENC_NS = 'urn:mpeg:cenc:2013'
WIDEVINE_UUID = 'edef8ba9-79d6-4ace-a3c8-27dcd51d21ed'
ET.register_namespace('', MPD_NS)
ET.register_namespace('cenc', CENC_NS)


class ManifestError(ValueError):
    """The supplied manifest does not contain supported VOD stream data."""


def _tag(name):
    return '{{{}}}{}'.format(MPD_NS, name)


def _cenc_tag(name):
    return '{{{}}}{}'.format(CENC_NS, name)


def _seconds(value):
    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        raise ManifestError('Die Manifestdauer fehlt oder ist ungültig.')
    if milliseconds <= 0:
        raise ManifestError('Die Manifestdauer muss größer als null sein.')
    return 'PT{:.3f}S'.format(milliseconds / 1000.0)


def _https_url(value):
    if not isinstance(value, str) or not value.startswith('https://'):
        raise ManifestError('Ein Stream enthält keine sichere HTTPS-Adresse.')
    return value


def _stream_url(stream):
    urls = stream.get('urls') or []
    if not urls or not isinstance(urls[0], dict):
        raise ManifestError('Für einen Stream fehlt die CDN-Adresse.')
    return _https_url(urls[0].get('url'))


def _codec(profile, kind):
    profile = str(profile or '').lower()
    if kind == 'audio':
        return 'ec-3' if 'ddplus-' in profile or 'dd-' in profile else 'mp4a.40.5'
    if profile.startswith('hevc-dv'):
        return 'dvhe'
    if profile.startswith('hevc'):
        return 'hev1'
    if profile.startswith('vp9-profile'):
        return 'vp09'
    if 'av1' in profile:
        return 'av01'
    return 'avc1'


def _add_segment_base(representation, stream):
    sidx = stream.get('sidx')
    if not isinstance(sidx, dict):
        return
    try:
        offset = int(sidx['offset'])
        size = int(sidx['size'])
    except (KeyError, TypeError, ValueError):
        raise ManifestError('Ungültige Segment-Index-Metadaten im Stream.')
    if offset <= 0 or size <= 0:
        raise ManifestError('Ungültige Segment-Index-Grenzen im Stream.')
    segment_base = ET.SubElement(
        representation, _tag('SegmentBase'),
        indexRange='{}-{}'.format(offset, offset + size), indexRangeExact='true',
    )
    ET.SubElement(segment_base, _tag('Initialization'), range='0-{}'.format(offset - 1))


def _add_protection(adaptation_set, video_track):
    header = video_track.get('drmHeader') or {}
    key_id = header.get('keyId')
    pssh = header.get('bytes')
    if key_id:
        try:
            key_bytes = base64.b64decode(key_id, validate=True)
            if len(key_bytes) != 16:
                raise ValueError('expected 16 bytes')
            normalized_key_id = str(uuid.UUID(bytes=key_bytes))
        except (ValueError, TypeError) as exc:
            raise ManifestError('Die Widevine-Key-ID im Manifest ist ungültig.') from exc
        value = 'cbcs' if any('av1' in str(item.get('content_profile') or '').lower()
                             for item in video_track.get('streams') or []) else 'cenc'
        ET.SubElement(
            adaptation_set, _tag('ContentProtection'),
            schemeIdUri='urn:mpeg:dash:mp4protection:2011',
            value=value,
            attrib={_cenc_tag('default_KID'): normalized_key_id},
        )
    protection = ET.SubElement(
        adaptation_set, _tag('ContentProtection'),
        schemeIdUri='urn:uuid:{}'.format(WIDEVINE_UUID), value='widevine',
    )
    if pssh:
        ET.SubElement(protection, _cenc_tag('pssh')).text = str(pssh)


def _append_video(mpd_period, track, drm_track):
    adaptation = ET.SubElement(
        mpd_period, _tag('AdaptationSet'), id='video', contentType='video',
        mimeType='video/mp4',
    )
    if drm_track:
        _add_protection(adaptation, track)
    for index, stream in enumerate(track.get('streams') or []):
        if bool(stream.get('isDrm')) != drm_track:
            continue
        try:
            width, height = int(stream['res_w']), int(stream['res_h'])
            bitrate = int(stream['bitrate']) * 1024
        except (KeyError, TypeError, ValueError):
            raise ManifestError('Video-Streamdaten sind unvollständig.')
        if width <= 0 or height <= 0 or bitrate <= 0:
            raise ManifestError('Videoauflösung oder Bitrate ist ungültig.')
        profile = stream.get('content_profile') or ''
        rep = ET.SubElement(
            adaptation, _tag('Representation'),
            id=str(stream.get('downloadable_id') or index),
            width=str(width), height=str(height), bandwidth=str(bitrate),
            codecs=_codec(profile, 'video'), mimeType='video/mp4',
        )
        ET.SubElement(rep, _tag('BaseURL')).text = _stream_url(stream)
        _add_segment_base(rep, stream)


def _append_audio(mpd_period, track, index):
    channels = {'1.0': '1', '2.0': '2', '5.1': '6', '7.1': '8'}
    language = str(track.get('language') or 'und')
    adaptation = ET.SubElement(
        mpd_period, _tag('AdaptationSet'), id='audio-{}'.format(index),
        contentType='audio', mimeType='audio/mp4', lang=language,
        original=str(bool(track.get('isNative'))).lower(),
    )
    if track.get('hasDrmStreams'):
        _add_protection(adaptation, track)
    for stream_index, stream in enumerate(track.get('streams') or []):
        try:
            bitrate = int(stream['bitrate']) * 1024
            channel_count = channels[str(stream['channels'])]
        except (KeyError, TypeError, ValueError):
            raise ManifestError('Audio-Streamdaten sind unvollständig.')
        if bitrate <= 0:
            raise ManifestError('Audio-Bitrate ist ungültig.')
        rep = ET.SubElement(
            adaptation, _tag('Representation'),
            id=str(stream.get('downloadable_id') or stream_index),
            bandwidth=str(bitrate), codecs=_codec(stream.get('content_profile'), 'audio'),
            mimeType='audio/mp4',
        )
        ET.SubElement(
            rep, _tag('AudioChannelConfiguration'),
            schemeIdUri='urn:mpeg:dash:23003:3:audio_channel_configuration:2011',
            value=channel_count,
        )
        ET.SubElement(rep, _tag('BaseURL')).text = _stream_url(stream)
        _add_segment_base(rep, stream)


def convert_vod_to_mpd(manifest):
    """Return UTF-8 MPD bytes for a basic Netflix VOD manifest.

    Ad-supported/branching manifests and text tracks are intentionally rejected
    or omitted until their playback and timeline handling is implemented.
    """
    if not isinstance(manifest, dict):
        raise ManifestError('Das Manifest hat ein ungültiges Format.')
    if manifest.get('streamingType', 'VOD') != 'VOD':
        raise ManifestError('Nur Video-on-Demand wird unterstützt.')
    if manifest.get('auxiliaryManifests'):
        raise ManifestError('Manifeste mit zusätzlichen Werbe-Streams werden noch nicht unterstützt.')
    video_tracks = manifest.get('video_tracks') or []
    if not video_tracks:
        raise ManifestError('Das Manifest enthält keine Videospuren.')

    root = ET.Element(
        _tag('MPD'),
        attrib={
            'type': 'static',
            'mediaPresentationDuration': _seconds(manifest.get('duration')),
            'minBufferTime': 'PT2S',
            'profiles': 'urn:mpeg:dash:profile:isoff-on-demand:2011',
        },
    )
    period = ET.SubElement(root, _tag('Period'), id=str(manifest.get('movieId') or 'video'))
    main_video = video_tracks[0]
    drm_track = bool(main_video.get('hasDrmStreams'))
    _append_video(period, main_video, drm_track)
    for index, track in enumerate(manifest.get('audio_tracks') or []):
        _append_audio(period, track, index)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)
