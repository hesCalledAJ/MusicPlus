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

[**Install from Telegram**](https://t.me/exteraPluginRepo?c=AJ_Plugins) · [**GitHub Releases**](https://github.com/hesCalledAJ/MusicPlus/releases/latest)

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
2. **Install the APK.**
3. **Log in** with your Telegram account, the same way you would in the regular app.
4. **Turn on plugins.** Open exteraGram **Preferences → Plugins** and enable the plugin engine.
5. **Check your version.** Music + needs exteraGram `12.10.6` or newer. Update the app if yours is older.

> [!NOTE]
> You might need to allow installing from **Unknown Sources** before Android lets you install the APK. [Here's how to enable it](https://t.me/exteraSettings?s=pluginsUnknownSources).
>
> Prefer not to enable it? You can [install from a known source](https://t.me/exteraPluginsSup/1196) instead. Updates there arrive later than on the official channels.

### Step 2 — Install Music +

Pick whichever method suits you.

#### Option A — From the Telegram plugin catalog (recommended)

1. **[Add AJ's plugins as a PLugin Repository](https://t.me/exteraPluginRepo?c=AJ_Plugins)** in exteraGram/AyuGram.
2. Find **Music +** and tap **Install**.
3. Enable the plugin.

#### Option B — Manual install from GitHub

1. Open the [latest release](https://github.com/hesCalledAJ/MusicPlus/releases/latest).
2. Download the `MusicPlus-vX.Y.elyx` file attached to it.
3. Send the file in any chat (Saved Messages works well) and tap it to install.
4. Confirm the install and enable Music +.

> [!TIP]
> By default, Music + replaces Telegram's built-in music player sheet. Turn on the **Music tab** in the plugin settings to get the full library interface.

### Requirements

| Component | Minimum |
|:--|:--|
| exteraGram | `12.10.6` |
| Plugin SDK | `1.4.4.3` |
| Package format | `.elyx` |

The SDK version is a plugin API requirement only. You don't need to install a separate SDK on your phone.

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
| **Releases** | [Latest GitHub release](https://github.com/hesCalledAJ/MusicPlus/releases/latest) |
| **ExteraGram** | [Website](https://exteragram.app) · [Telegram](https://t.me/exteraGram) · [Plugin documentation](https://plugins.exteragram.app/docs) |
| **AyuGram** | [Android repository](https://github.com/AyuGram/AyuGram4A) · [Telegram](https://t.me/ayugram) |

## 🤝 Contributing

Contributions are welcome, whether it's a bug report, a translation, or a code change.

### Report a bug or suggest a feature

Open an [issue](https://github.com/hesCalledAJ/MusicPlus/issues) and include:

- what you expected and what happened instead;
- your exteraGram version and your Music + version;
- steps to reproduce it, plus a screenshot if it helps.

### Add or fix a translation

1. Fork the repository.
2. Edit the file for your language in `MusicPlus/strings/` (`strings_en.yml`, `strings_fa.yml` or `strings_ru.yml`). For a new language, copy `strings_en.yml` and translate it.
3. Open a pull request.

### Send a code change

1. Fork the repository and create a branch.
2. Make your changes under `MusicPlus/`.
3. [Build it locally](#-for-developers) and try it in exteraGram.
4. Open a pull request that explains what you changed and why.

Please don't change `version` in `MusicPlus/metainfo.yml` or edit `extera-plugins.json` in a pull request. Those are updated when a release is published.

## 🧩 For developers

### Build locally

```bash
python -m pip install pyyaml
python scripts/build_elyx.py
```

This checks the Python syntax and writes `dist/MusicPlus-vX.Y.elyx`. Install that file the same way as in [Option B](#option-b--manual-install-from-github).

### Publish a release (maintainers)

1. Update `version` in `MusicPlus/metainfo.yml` and push.
2. Create a GitHub Release with a matching tag and a `v` prefix (version `1.6` → tag `v1.6`).

The `release.yml` workflow does the rest: it builds the `.elyx`, attaches it to the release, and updates `extera-plugins.json` with the download URL, SHA-256 and size.

For compiled builds, see the [official ElyxBuilder docs](https://plugins.exteragram.app/docs/elyx/elyxbuilder).

## 💬 Support

For updates, announcements, and help, visit **[@AJ_Plugins](https://t.me/AJ_Plugins)**.

---

<div align="center">

Made for music lovers who never leave Telegram. 🎶

**Music + · by [AJ](https://t.me/AJ_Plugins)**

</div>
