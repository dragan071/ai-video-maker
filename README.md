# AI Video Maker

A small desktop app for creating videos with the **xAI / Grok Imagine** or **Google Gemini Omni Flash** API. Type a prompt or pick your own image, and the app waits for the result and saves the MP4 to a folder you choose.

## Features

- provider choice: **xAI / Grok** or **Google / Gemini**
- mode: **text → video** or **image → video**
- PNG, JPEG and WebP source images from disk
- separate xAI and Google API key storage
- each provider remembers its own model, duration, aspect ratio and resolution
- libadwaita interface with the same white header bar as other Fedora/GNOME apps
- automatic MP4 saving and folder opening
- no extra `pip` packages; uses the official REST APIs

### Supported options

| Option | xAI / Grok | Google / Gemini |
|---|---|---|
| Models | `grok-imagine-video-1.5`, `grok-imagine-video-1.5-lite`, `grok-imagine-video` | `gemini-omni-1.2-flash` |
| Text → video | Yes | Yes |
| Image → video | Yes | Yes |
| Duration | 1–15 seconds | 3–15 seconds |
| Aspect ratio | 16:9, 9:16, 1:1, 4:3, 3:4, 3:2, 2:3, 21:9, 5:2 | 16:9 and 9:16 |
| Aspect ratio with a source image | Automatic, follows the image | You choose 16:9 or 9:16 |
| Resolution | 480p, 720p, 1080p; the legacy model up to 720p | 360p, 720p, 1080p and 4K |
| Audio | Can be turned on or off | Always on |

According to the official documentation, Google's 1080p and 4K output is upscaled from a lower resolution.

## Running

You need Python 3.10 or newer, GTK4, **libadwaita** and PyGObject.

```bash
cd ai-video-maker
python3 app.py
```

If GTK/PyGObject are missing on another Linux machine:

```bash
# Fedora
sudo dnf install python3-gobject gtk4 libadwaita python3-libadwaita

# Ubuntu / Debian
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

No `pip` packages are required.

## API keys

You do not need both keys — enter only the one for the service you want to use.

- **xAI:** create a key in the [xAI Console](https://console.x.ai/).
- **Google:** create a key in [Google AI Studio](https://aistudio.google.com/apikey). Gemini Omni Flash requires billing enabled on the Google Cloud project; the model is not available on the free API tier.

Keys are shown as a password; the icon next to the field reveals them.

## Text → video

1. Choose a provider and the **Text → video** mode.
2. Paste the matching API key.
3. Write a prompt. It helps to describe the scene, motion, camera, lighting and the sound you want.
4. Pick the model, duration, aspect ratio and resolution.
5. Press **Generate video** and keep the app open until the MP4 is saved.

## Image → video

1. Choose the **Image → video** mode.
2. Press **Choose…** next to **Source image** and pick a PNG, JPEG or WebP file.
3. In the prompt, describe how the image should be animated, e.g. "Slowly zoom in, leaves sway in the wind, the person blinks and smiles".
4. Pick the remaining options and press **Generate video**.

With Grok, the output video automatically follows the source image's aspect ratio. With Google, you can choose 16:9 or 9:16.

## Saving and files

Settings and keys are saved when you press **Save settings**, when generation starts, and when the window closes. The default video folder is `videos` inside the project.

Example file names:

```text
videos/grok_20261125_183000_a1b2c3d4.mp4
videos/google_20261125_184500_v1_abc123.mp4
```

## Privacy and cost

- Both keys are stored as **plain text** in the local `grok_video_settings.json` file next to the app. On Linux the app sets its permission to `600`; do not share or send that file to anyone.
- That file is listed in `.gitignore` and must never end up in the repository. If a key leaks anyway, revoke it immediately in the xAI Console or Google AI Studio.
- The prompt and the selected image are sent to the chosen provider for generation.
- Generation is billed according to the provider's pricing; model, duration and resolution all affect the cost.
- If you close the app while a request is running, local waiting and saving stop, but an already submitted API request may still be billed.
- The app currently does not support editing an existing video, extending a video, multiple reference images, or Genie interactive worlds.

Documentation:

- [xAI Video Generation](https://docs.x.ai/developers/model-capabilities/video/generation)
- [xAI Image-to-Video](https://docs.x.ai/developers/model-capabilities/video/image-to-video)
- [Google Gemini Omni Flash](https://ai.google.dev/gemini-api/docs/omni)

## Tests

The tests use mocked API responses and do not spend any credit:

```bash
python3 -m unittest discover -s tests -v
```

## Disclaimer

This is an unofficial personal project. It is not affiliated with xAI, Google, the GNOME project or Fedora, and it is not an official product of any of them. "Grok", "Gemini" and other names are the property of their respective owners.

## License

[MIT](LICENSE)
