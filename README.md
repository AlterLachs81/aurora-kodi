# Aurora for Kodi

Aurora is being rewritten as a standalone Kodi Netflix add-on. The development branch is `rewrite/standalone-prototype`.

## Development status

The prototype now contains Aurora-owned code for importing an `NFAuthentication.key`, storing its Netflix cookies, checking the session directly with Netflix, and requesting catalogue data. Kodi navigation no longer calls `plugin.video.netflix`.

An initial Kodi InputStream Adaptive hand-off for a resolved DASH manifest and Widevine license endpoint is in `resources/lib/aurora/player.py`. It is only the Kodi-facing adapter: Aurora still does not create Netflix's MSL manifest or license requests, and the adapter is not connected to title selection. A cookie session alone is not a playback implementation.

The prototype branch is not an installable update. The stable repository feed remains on `main` until the independent login, catalogue and playback flow is complete and checked on LibreELEC.

## Local repository build

After a release version is ready, update the add-on version in `plugin.video.netflix.aurora/addon.xml` and `PLUGIN_VERSION` in `build_repository.py`, then run:

```sh
python3 build_repository.py --base-url https://raw.githubusercontent.com/AlterLachs81/aurora-kodi/main
```

Commit the generated `addons.xml`, `addons.xml.md5`, and versioned ZIPs in `addons/` with the source.
