# Aurora for Kodi

Aurora is being rewritten as a standalone Kodi Netflix add-on. The development branch is `rewrite/standalone-prototype`.

## Development status

The prototype now contains Aurora-owned code for importing an `NFAuthentication.key`, storing its Netflix cookies, checking the session directly with Netflix, and requesting catalogue data. Kodi navigation no longer calls `plugin.video.netflix`.

The playback groundwork has three separate pieces: `resources/lib/aurora/msl.py` contains an initial MSL key-exchange and encrypted-request transport; `resources/lib/aurora/dash_manifest.py` converts a limited, already-resolved VOD manifest into DASH; and `resources/lib/aurora/player.py` hands a resolved MPD plus Widevine license endpoint to Kodi InputStream Adaptive. The MSL and DASH code are not connected to title selection, the Kodi challenge callback, or license handling, and none of this has been tested against Netflix or LibreELEC yet. The converter rejects manifests with auxiliary ad streams and does not add subtitle tracks. This remains a development prototype, not a playable update.

The prototype branch is not an installable update. The stable repository feed remains on `main` until the independent login, catalogue and playback flow is complete and checked on LibreELEC.

## Local repository build

After a release version is ready, update the add-on version in `plugin.video.netflix.aurora/addon.xml` and `PLUGIN_VERSION` in `build_repository.py`, then run:

```sh
python3 build_repository.py --base-url https://raw.githubusercontent.com/AlterLachs81/aurora-kodi/main
```

Commit the generated `addons.xml`, `addons.xml.md5`, and versioned ZIPs in `addons/` with the source.
