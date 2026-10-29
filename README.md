# Aurora for Kodi

Aurora is being rewritten as a standalone Kodi Netflix add-on. The development branch is `rewrite/standalone-prototype`.

## Development status

The prototype now contains Aurora-owned code for importing an `NFAuthentication.key`, storing its Netflix cookies, checking the session directly with Netflix, and requesting catalogue data. Kodi navigation no longer calls `plugin.video.netflix`.

The playback path is now wired in code: title selection hands the stream to Kodi InputStream Adaptive; the add-on service exposes loopback-only manifest and license callbacks; and Aurora's MSL client exchanges the Widevine challenge with Netflix. The DASH converter handles only a limited VOD manifest, rejects auxiliary ad streams, and omits subtitle tracks. **This end-to-end path has not been tested against Netflix or LibreELEC and is not known to work yet.** Treat it as a development prototype, not a playable update.

Version 0.4.0 is available through the existing **Aurora Add-on Repository**. It is installable as a Kodi add-on, but the Netflix playback path is unverified and must be treated as experimental.

## Build the repository feed

Build the packages and feed with:

```sh
python3 build_repository.py --base-url https://raw.githubusercontent.com/AlterLachs81/aurora-kodi/main
```

Open **Aurora Add-on Repository** in Kodi and update **Aurora for Netflix** to version 0.4.0.

The automated tests mock Netflix and Kodi callbacks; neither a real MSL login nor Widevine playback on LibreELEC has been validated. A LibreELEC/Kodi 21 device and a Netflix session are still needed for that playback check.
