# Aurora for Kodi

Aurora is an independent Kodi add-on for navigating Netflix with Kodi's native directory interface. It includes its own category menu, search entry point, local favorites and recently started list.

## Netflix service integration

Aurora's interface and navigation are implemented here. In version 0.3.0, Netflix catalogue data and playback are provided by the installed `plugin.video.netflix` add-on through Kodi's plugin interface. Aurora does not copy CastagnaIT's internal implementation.

This separation means a failure in the Netflix add-on, account session, DRM or video decoder can still prevent catalogue access or playback. Replacing that service layer requires a separate Netflix authentication, MSL and DRM implementation; a new Kodi interface alone cannot fix those systems.

## Install in Kodi

1. Install `addons/repository.aurora/repository.aurora-1.0.0.zip` once via **Add-ons → Install from ZIP file**.
2. Open **Install from repository → Aurora Add-on Repository → Video add-ons → Aurora for Netflix**.
3. Kodi can then install and update Aurora through the repository.

## Build the feed

After changing the add-on version in `plugin.video.netflix.aurora/addon.xml`, update `PLUGIN_VERSION` in `build_repository.py`, then run:

```sh
python3 build_repository.py --base-url https://raw.githubusercontent.com/AlterLachs81/aurora-kodi/main
```

Commit the generated `addons.xml`, `addons.xml.md5`, and versioned ZIPs in `addons/` with the source.
