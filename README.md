<p align="center">
  <img src="assets/musicplus-banner.png" alt="Music + — The Music Player Telegram Deserved" width="100%">
</p>

<div align="center">

# Music +

### The Music Player Telegram Deserved.

A richer music experience inside Telegram — with a personal library, lyrics, and much better control over what plays next.

[![Latest release](https://img.shields.io/github/v/release/hesCalledAJ/MusicPlus?style=for-the-badge&label=VERSION)](https://github.com/hesCalledAJ/MusicPlus/releases)
[![Client](https://img.shields.io/badge/PLUGIN%20FOR-EXTERAGRAM-5661e8?style=for-the-badge)](https://exteragram.app)
[![Format](https://img.shields.io/badge/PACKAGE-ELYX-8b5cf6?style=for-the-badge)](https://plugins.exteragram.app/docs/elyx)
[![Languages](https://img.shields.io/badge/LANGUAGES-EN%20%7C%20RU%20%7C%20FA-0f9d78?style=for-the-badge)](#-languages)
[![Channel](https://img.shields.io/badge/TELEGRAM-AJ__PLUGINS-229ED9?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/AJ_Plugins)

[**Install from Telegram**](https://t.me/exteraPluginRepo?c=AJ_Plugins) · [**GitHub Releases**](https://github.com/hesCalledAJ/MusicPlus/releases/latest) · [**Installation guide**](https://t.me/AJ_Plugins/41)

</div>

---

## ✨ What's inside

<table>
  <tr>
    <td width="50%">
      <h3>🎧 Your music library</h3>
      Browse liked and downloaded tracks, playlists, chats, topics, friends, and artists. Switch between grid and list views, search, sort, and organize your collection.
    </td>
    <td width="50%">
      <h3>📜 Lyrics that keep up</h3>
      A dedicated lyrics view with scrolling, timing adjustment, resync controls, and right-to-left text support.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <h3>🪄 Queue control</h3>
      Reorder tracks, play something next, add tracks to the end, shuffle, repeat, lock the queue, and restore your last queue.
    </td>
    <td width="50%">
      <h3>🎚️ Playback tools</h3>
      Equalizer, crossfade, per-track speed and pitch controls, and a sleep timer — all close to the player.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <h3>📦 Playlists & transfers</h3>
      Create and manage playlists, share playlists with other Music + users, and move music between your library and Telegram profile music.
    </td>
    <td width="50%">
      <h3>💾 Backup & downloads</h3>
      Batch download tracks, manage downloaded music, and export or import Music + data and settings.
    </td>
  </tr>
</table>

## 📱 Installation

Music + is a **plugin for exteraGram**, so you need exteraGram first. Set that up once, then install Music + in under a minute.

### Step 1 — Set up exteraGram

> [!NOTE]
> exteraGram is an **Android** Telegram client. There is no iOS or desktop build.

1. **Download exteraGram** from one of its official sources:
   - [exteragram.app](https://exteragram.app)
   - [@exteraGram](https://t.me/exteraGram) (news and updates)
   - [@exteraReleases](https://t.me/exteraReleases) (APK downloads)
2. **Install the APK.** If Android asks, allow installs from your browser or from Telegram.
3. **Log in** with your Telegram account, the same way you would in the regular app.
4. **Turn on plugins.** Open exteraGram **Preferences → Plugins** and enable the plugin engine.
5. **Check your version.** Music + needs exteraGram `12.10.6` or newer. Update the app if yours is older.

### Step 2 — Install Music +

Pick whichever method suits you.

#### Option A — From the Telegram plugin catalog (recommended)

1. Tap **[Add Music +](https://t.me/exteraPluginRepo?c=AJ_Plugins)** to open the AJ Plugins repository in exteraGram.
2. Find **Music +** and tap **Install**.
3. Enable the plugin.
4. Open Music + settings, turn on the **Music tab**, and restart exteraGram.

#### Option B — Manual install from GitHub

1. Open the [latest release](https://github.com/hesCalledAJ/MusicPlus/releases/latest).
2. Download the `MusicPlus-vX.Y.elyx` file attached to it.
3. Open the file with exteraGram's plugin installer, or use the import action in **Preferences → Plugins**.
4. Confirm the install and enable Music +.
5. Open Music + settings, turn on the **Music tab**, and restart exteraGram.

> [!TIP]
> By default, Music + replaces Telegram's built-in music player sheet. Turn on the **Music tab** in the plugin settings to get the full library interface.

> [!NOTE]
> The `.elyx` file is built and attached to each GitHub Release automatically. It is not committed to this repository.

### Requirements

| Component | Minimum |
|:--|:--|
| exteraGram | `12.10.6` |
| Plugin SDK | `1.4.4.3` |
| Package format | `.elyx` |

The SDK version is a plugin API requirement only. You don't need to install a separate SDK on your phone.

Need a walkthrough with screenshots? See the [installation guide](https://t.me/AJ_Plugins/41).

## 🗂️ Project structure

```text
.
├── .github/
│   └── workflows/
│       └── release.yml              # Builds, attaches and indexes each release
├── assets/
│   └── musicplus-banner.png         # Repository banner
├── MusicPlus/                       # Unpacked Elyx project (source of truth)
│   ├── refmap.yml                   # Elyx entry-point and resource map
│   ├── metainfo.yml                 # Plugin metadata and version
│   ├── strings/
│   │   ├── strings_en.yml           # English
│   │   ├── strings_fa.yml           # Persian
│   │   └── strings_ru.yml           # Russian
│   └── musicplus/
│       ├── main.py                  # Main player / queue integration
│       ├── tabs.py                  # Music tab integration
│       ├── sheets.py                # Player and library sheets
│       ├── editor/                  # Library, header and playback editors
│       ├── features/                # Playlists, sync, downloads and playback
│       └── ...                      # Supporting modules
├── scripts/
│   ├── build_elyx.py                # Creates dist/MusicPlus-vX.Y.elyx
│   └── update_index.py              # Writes release URL, SHA-256 and size
├── extera-plugins.json              # ExteraGram catalog index (updated on release)
└── README.md
```

Generated output such as `dist/`, `.pyc` files, and local ElyxBuilder caches is ignored by Git.

## 🌐 Languages

The interface currently includes:

- 🇬🇧 English
- 🇮🇷 Persian
- 🇷🇺 Russian

## 🔗 Links

| | Link |
|:--|:--|
| **Author / updates** | [AJ Plugins](https://t.me/AJ_Plugins) |
| **Music + installation guide** | [Read the guide](https://t.me/AJ_Plugins/41) |
| **Releases** | [Latest GitHub release](https://github.com/hesCalledAJ/MusicPlus/releases/latest) |
| **ExteraGram** | [Website](https://exteragram.app) · [Telegram](https://t.me/exteraGram) · [Plugin documentation](https://plugins.exteragram.app/docs) |
| **AyuGram** | [Android repository](https://github.com/AyuGram/AyuGram4A) · [Telegram](https://t.me/ayugram) |

> **Compatibility note:** Music + is packaged for the ExteraGram plugin API. AyuGram is linked as a related ExteraGram-based client; compatibility with a particular AyuGram build is not guaranteed here.

## 🧩 For developers

### Build locally

The repository includes a small, dependency-light packager. It validates Python syntax, reads the version from `MusicPlus/metainfo.yml`, and creates a source archive with `refmap.yml` at the archive root.

```bash
python -m pip install pyyaml
python scripts/build_elyx.py
```

The output is written to `dist/MusicPlus-vX.Y.elyx`. The `dist/` directory is ignored by Git.

### Publish a release

1. Make your changes under `MusicPlus/`.
2. Update `version` in `MusicPlus/metainfo.yml`.
3. Commit and push the source changes.
4. Create a GitHub Release with a tag matching the metadata version, using the `v` prefix (for example, metadata `1.6` → tag `v1.6`).
5. Publish the release.

The `release.yml` workflow then:

- builds the `.elyx` from the checked-out release tag;
- attaches it to that GitHub Release;
- calculates its SHA-256 and exact byte size;
- updates `extera-plugins.json` on the default branch with the GitHub Release asset URL.

No `.elyx` binary needs to be committed or uploaded manually. The ExteraGram catalog uses the release asset URL and verifies its size and SHA-256 before installation.

### Manual catalog-index generation

After building, you can generate the index entry yourself:

```bash
python scripts/update_index.py \
  --archive dist/MusicPlus-v1.5.elyx \
  --asset-url "https://github.com/hesCalledAJ/MusicPlus/releases/download/v1.5/MusicPlus-v1.5.elyx"
```

The official ElyxBuilder is also supported for more advanced builds. This repository's packager creates a source archive, matching the current source-based `.elyx` package. For compiled `.pyc` builds, use Python 3.11 and ElyxBuilder as described in the [official build docs](https://plugins.exteragram.app/docs/elyx/elyxbuilder).

## 💬 Support

For updates, announcements, and help, visit **[@AJ_Plugins](https://t.me/AJ_Plugins)**.

---

<div align="center">

Made for music lovers who never leave Telegram. 🎶

**Music + · by [AJ](https://t.me/AJ_Plugins)**

</div>
