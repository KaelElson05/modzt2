# 📜 Changelog
All notable changes to **ModZT2** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.6] - 2025-11-02
###Added
- ZT1 support (.ztd files)
- In-game ZT2 Screenshot manager

###Changed
- Renamed from ModZT2 to ModZT

## [1.0.2] - 2025-10-26
###Added
- Player to player species transfer market prototype
- Data folder for zoo save file species

###Fixed
- Mod list UI gap

## [1.0.0] - 2025-10-26
###Added
- Auto-detection of Zoo Tycoon 2 installation from common paths
- Persistent `settings.json` with theme and geometry memory
- Threaded `run_with_progress()` to prevent UI freezing
- SQLite database (`mods.db`) for mod and bundle tracking
- Toolbar menus (Game / Mods / Tools / View / Help)
- Tabs:
  - **Mods** — view and manage mods
  - **Bundles** — create and export loadouts
- Theme toggle (light/dark)
- MIT License and full documentation

###Changed
- Improved error handling and auto-creation of default settings

###Fixed
- UI freezing during long operations (now fully threaded)
- Game path detection reliability

---

###Planned features
- Mod metadata reader (`.z2f`, `.zip`)
- Online mod downloader / repository integration with mod install links
- Auto-update & version check system


