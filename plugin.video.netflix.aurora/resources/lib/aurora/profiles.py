# -*- coding: utf-8 -*-
"""Conservative H.264/AAC profile request for the first Raspberry Pi path."""


def enabled_profiles():
    """Return the initial browser-compatible profile set used for MSL VOD."""
    return [
        'heaac-2-dash',
        'heaac-2hq-dash',
        'BIF240',
        'BIF320',
        'playready-h264mpl30-dash',
        'playready-h264mpl31-dash',
        'playready-h264mpl40-dash',
        'playready-h264hpl22-dash',
        'playready-h264hpl30-dash',
        'playready-h264hpl31-dash',
        'playready-h264hpl40-dash',
        'webvtt-lssdh-ios8',
    ]
