import base64
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

PLUGIN = Path(__file__).resolve().parents[1] / 'plugin.video.netflix.aurora'
sys.path.insert(0, str(PLUGIN))

from resources.lib.aurora.dash_manifest import ManifestError, convert_vod_to_mpd  # noqa: E402


NS = {'mpd': 'urn:mpeg:dash:schema:mpd:2011', 'cenc': 'urn:mpeg:cenc:2013'}


def sample_manifest():
    key_id = base64.b64encode(b'\x00' * 16).decode('ascii')
    stream_url = 'https://cdn.netflix.com/title/video.mp4'
    return {
        'movieId': '12345',
        'duration': 60_000,
        'streamingType': 'VOD',
        'video_tracks': [{
            'hasDrmStreams': True,
            'drmHeader': {'keyId': key_id, 'bytes': 'cHNzaA=='},
            'streams': [{
                'isDrm': True, 'res_w': 1280, 'res_h': 720, 'bitrate': 1800,
                'content_profile': 'playready-h264hpl31-dash', 'downloadable_id': 'v1',
                'urls': [{'url': stream_url}], 'sidx': {'offset': 1024, 'size': 64},
            }],
        }],
        'audio_tracks': [{
            'hasDrmStreams': True,
            'drmHeader': {'keyId': key_id, 'bytes': 'cHNzaA=='},
            'language': 'de-DE', 'isNative': True,
            'streams': [{
                'bitrate': 128, 'channels': '2.0', 'content_profile': 'heaac-2-dash',
                'downloadable_id': 'a1', 'urls': [{'url': stream_url}],
            }],
        }],
    }


class DashManifestTests(unittest.TestCase):
    def test_converts_video_audio_and_widevine_metadata(self):
        root = ET.fromstring(convert_vod_to_mpd(sample_manifest()))
        self.assertEqual(root.attrib['type'], 'static')
        self.assertEqual(root.attrib['mediaPresentationDuration'], 'PT60.000S')
        self.assertEqual(len(root.findall('.//mpd:Representation', NS)), 2)
        self.assertEqual(root.find('.//mpd:BaseURL', NS).text, 'https://cdn.netflix.com/title/video.mp4')
        self.assertEqual(root.find('.//mpd:SegmentBase', NS).attrib['indexRange'], '1024-1088')
        self.assertIsNotNone(root.find('.//mpd:ContentProtection[@value="widevine"]', NS))
        self.assertIsNotNone(root.find('.//cenc:pssh', NS))

    def test_rejects_auxiliary_ad_streams(self):
        manifest = sample_manifest()
        manifest['auxiliaryManifests'] = [{'isAd': True}]
        with self.assertRaises(ManifestError):
            convert_vod_to_mpd(manifest)

    def test_rejects_non_https_stream_urls(self):
        manifest = sample_manifest()
        manifest['video_tracks'][0]['streams'][0]['urls'][0]['url'] = 'http://example.invalid/v.mp4'
        with self.assertRaises(ManifestError):
            convert_vod_to_mpd(manifest)


if __name__ == '__main__':
    unittest.main()
