# Aurora for Kodi

Kodi repository for `plugin.video.netflix.aurora`. Aurora provides its own Kodi interface and uses the separately installed `plugin.video.netflix` add-on for catalogue access and playback.

## Install in Kodi

1. Install `addons/repository.aurora/repository.aurora-1.0.0.zip` once via **Add-ons → Install from ZIP file**.
2. Open **Install from repository → Aurora Add-on Repository → Video add-ons → Aurora for Netflix**.
3. Kodi can then install and update Aurora through the repository.

## Build the feed

After changing the add-on version in `addon.xml`, update the matching version constant in `build_repository.py`, then run:

```sh
python3 build_repository.py --base-url https://raw.githubusercontent.com/AlterLachs81/aurora-kodi/main
```

Commit the generated `addons.xml`, `addons.xml.md5`, and ZIP packages in `addons/` together with the source.

Aurora targets Kodi Omega / Python 3 and requires the existing `plugin.video.netflix` add-on. This repository does not include CastagnaIT's add-on or Netflix credentials.
