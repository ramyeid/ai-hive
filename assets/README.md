# Hive assets

The logo: a soft sage hexagon with five hive cells forming an **H**: cream cells, a honey centre.
Same colours in light and dark mode.

| Colour | Hex |
|---|---|
| Sage (the hexagon) | `#76a891` |
| Cream (the cells) | `#fbf7ec` |
| Honey (the centre cell) | `#f5cc72` |

## Which file for what

| Use | File |
|---|---|
| **Slack app icon** (api.slack.com/apps → your app → Basic Information → Display Information → App icon; 512–2000 px square) | `app-icon-sage-1024.png` |
| Website favicon (browser tab) | `favicon.ico` (16, 32, 48 px), or `hive-logo.svg` for modern browsers |
| iPhone / iPad home screen | `apple-touch-icon.png` (180 px) |
| Android / installable web app | `hive-logo-192.png`, `hive-logo-512.png`; `icon-maskable-192.png`, `icon-maskable-512.png` (safe for circle crops) |
| The logo anywhere else (docs, slides, avatars) | `hive-logo.svg` (scales to any size), or `hive-logo-1024.png` (transparent) |
| Logo with the name | `hive-wordmark-light.svg/png` (on light backgrounds), `hive-wordmark-dark.svg/png` (on dark) |
| Square app icons with a background (stores, GitHub org/repo avatar, Slack) | `app-icon-sage-512.png`, `app-icon-sage-1024.png` |

The SVGs are the masters: the PNGs are rendered from them. The console serves this folder at `/assets/`.
