#!/usr/bin/env python3
"""libadwaita desktop interface for Grok and Google video generation."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import NoReturn


def _exit_missing_gui(detail: str) -> NoReturn:
    """Print a friendly message instead of a traceback when GTK is unavailable."""
    sys.stderr.write(
        "AI Video Maker requires Linux with GTK4 and libadwaita (PyGObject).\n"
        f"\nMissing dependency: {detail}\n"
        "\nInstall it with:\n"
        "  Fedora:         sudo dnf install python3-gobject gtk4 libadwaita python3-libadwaita\n"
        "  Ubuntu/Debian:  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1\n"
        "\nOn Windows, run the app inside WSL2 (Windows 11 includes WSLg):\n"
        "  https://github.com/dragan071/ai-video-maker#running\n"
    )
    raise SystemExit(1)


try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Gtk
except (ImportError, ValueError) as exc:
    _exit_missing_gui(str(exc) or "PyGObject, GTK4 or libadwaita is not installed")

from google_api import (
    GOOGLE_ASPECT_RATIOS,
    GOOGLE_VIDEO_MODELS,
    GoogleAPIError,
    GoogleVideoClient,
)
from grok_api import (
    ASPECT_RATIOS,
    VIDEO_MODELS,
    GrokAPIError,
    GrokVideoClient,
    make_video_path,
)
from image_input import ImageInputError
from settings import SettingsError, SettingsStore


PROVIDER_LABELS = {
    "grok": "xAI / Grok",
    "google": "Google / Gemini",
}

MODE_LABELS = {
    "text": "Text → video",
    "image": "Image → video",
}


class VideoMakerWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="AI Video Maker")
        self.set_default_size(760, 860)
        self.set_resizable(True)

        self.settings_store = SettingsStore()
        self._is_generating = False
        self._closing = False
        self._updating_ui = False
        self._folder_dialog = None
        self._image_dialog = None

        load_warning = ""
        try:
            self.settings = self.settings_store.load()
        except SettingsError as exc:
            self.settings = self.settings_store.defaults()
            load_warning = str(exc)

        self._current_provider = self.settings["provider"]
        self._provider_options = {
            "grok": {
                "model": self.settings["model"],
                "duration": self.settings["duration"],
                "aspect_ratio": self.settings["aspect_ratio"],
                "resolution": self.settings["resolution"],
                "generate_audio": self.settings["generate_audio"],
            },
            "google": {
                "model": self.settings["google_model"],
                "duration": self.settings["google_duration"],
                "aspect_ratio": self.settings["google_aspect_ratio"],
                "resolution": self.settings["google_resolution"],
            },
        }

        self._build_interface()
        self._apply_settings()
        self.connect("close-request", self._on_close_request)

        if load_warning:
            self.status_label.set_text(load_warning + " Using default settings.")

    def _build_interface(self) -> None:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for margin in ("top", "bottom", "start", "end"):
            getattr(content, f"set_margin_{margin}")(20)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(content)

        # libadwaita gives the same white title bar and style as other Fedora apps.
        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(title="AI Video Maker", subtitle="Grok & Google Gemini")
        )
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(scroll)
        self.set_content(view)

        subtitle = Gtk.Label(
            label="Create an MP4 with Grok or Google, from text or your own image.",
            xalign=0,
        )
        subtitle.set_wrap(True)
        content.append(subtitle)

        self.prompt_label = Gtk.Label(xalign=0)
        content.append(self.prompt_label)

        prompt_scroll = Gtk.ScrolledWindow()
        prompt_scroll.set_min_content_height(110)
        prompt_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.prompt_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.prompt_view.set_accepts_tab(False)
        self.prompt_view.set_tooltip_text(
            "Describe the scene, motion, camera, lighting and sound. "
            "For images, describe how the scene should be animated."
        )
        for margin in ("top", "bottom", "left", "right"):
            getattr(self.prompt_view, f"set_{margin}_margin")(8)
        prompt_scroll.set_child(self.prompt_view)
        content.append(prompt_scroll)

        self.options_grid = Gtk.Grid(column_spacing=12, row_spacing=12)
        self.options_grid.set_hexpand(True)
        content.append(self.options_grid)
        grid = self.options_grid

        grid.attach(self._field_label("Provider"), 0, 0, 1, 1)
        self.provider_combo = Gtk.ComboBoxText()
        self.provider_combo.set_hexpand(True)
        for provider_id, label in PROVIDER_LABELS.items():
            self.provider_combo.append(provider_id, label)
        self.provider_combo.connect("changed", self._on_provider_changed)
        grid.attach(self.provider_combo, 1, 0, 1, 1)

        grid.attach(self._field_label("Mode"), 0, 1, 1, 1)
        self.mode_combo = Gtk.ComboBoxText()
        self.mode_combo.set_hexpand(True)
        for mode_id, label in MODE_LABELS.items():
            self.mode_combo.append(mode_id, label)
        self.mode_combo.connect("changed", self._on_mode_changed)
        grid.attach(self.mode_combo, 1, 1, 1, 1)

        self.api_key_label = self._field_label("API key")
        grid.attach(self.api_key_label, 0, 2, 1, 1)
        self.api_stack = Gtk.Stack()
        self.api_stack.set_hexpand(True)
        self.xai_api_entry = self._password_entry("API key from xAI Console")
        self.google_api_entry = self._password_entry("API key from Google AI Studio")
        self.api_stack.add_named(self.xai_api_entry, "grok")
        self.api_stack.add_named(self.google_api_entry, "google")
        grid.attach(self.api_stack, 1, 2, 1, 1)

        grid.attach(self._field_label("Model"), 0, 3, 1, 1)
        self.model_combo = Gtk.ComboBoxText()
        self.model_combo.set_hexpand(True)
        self.model_combo.connect("changed", self._on_model_changed)
        grid.attach(self.model_combo, 1, 3, 1, 1)

        self.image_label = self._field_label("Source image")
        grid.attach(self.image_label, 0, 4, 1, 1)
        self.image_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.image_entry = Gtk.Entry()
        self.image_entry.set_hexpand(True)
        self.image_entry.set_tooltip_text("PNG, JPEG or WebP image from your disk")
        self.image_box.append(self.image_entry)
        image_button = Gtk.Button(label="Choose…")
        image_button.connect("clicked", self._choose_image)
        self.image_box.append(image_button)
        grid.attach(self.image_box, 1, 4, 1, 1)

        grid.attach(self._field_label("Duration"), 0, 5, 1, 1)
        duration_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        adjustment = Gtk.Adjustment(value=8, lower=1, upper=15, step_increment=1, page_increment=1)
        self.duration_spin = Gtk.SpinButton(adjustment=adjustment, numeric=True)
        duration_box.append(self.duration_spin)
        duration_box.append(Gtk.Label(label="seconds"))
        grid.attach(duration_box, 1, 5, 1, 1)

        grid.attach(self._field_label("Aspect ratio"), 0, 6, 1, 1)
        self.aspect_stack = Gtk.Stack()
        self.aspect_stack.set_hexpand(True)
        self.aspect_combo = Gtk.ComboBoxText()
        self.aspect_combo.set_hexpand(True)
        self.aspect_stack.add_named(self.aspect_combo, "choice")
        automatic_aspect = Gtk.Label(label="Automatic — same as the source image", xalign=0)
        self.aspect_stack.add_named(automatic_aspect, "automatic")
        grid.attach(self.aspect_stack, 1, 6, 1, 1)

        grid.attach(self._field_label("Resolution"), 0, 7, 1, 1)
        self.resolution_combo = Gtk.ComboBoxText()
        self.resolution_combo.set_hexpand(True)
        grid.attach(self.resolution_combo, 1, 7, 1, 1)

        grid.attach(self._field_label("Audio"), 0, 8, 1, 1)
        self.audio_stack = Gtk.Stack()
        self.audio_stack.set_hexpand(True)
        self.audio_check = Gtk.CheckButton(label="Generate an audio track")
        self.audio_stack.add_named(self.audio_check, "grok")
        self.audio_stack.add_named(
            Gtk.Label(label="Audio is enabled automatically", xalign=0),
            "google",
        )
        grid.attach(self.audio_stack, 1, 8, 1, 1)

        grid.attach(self._field_label("Video folder"), 0, 9, 1, 1)
        folder_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.folder_entry = Gtk.Entry()
        self.folder_entry.set_hexpand(True)
        folder_box.append(self.folder_entry)
        choose_button = Gtk.Button(label="Choose…")
        choose_button.connect("clicked", self._choose_folder)
        folder_box.append(choose_button)
        grid.attach(folder_box, 1, 9, 1, 1)

        privacy_note = Gtk.Label(
            label="Both API keys and the settings are stored locally in "
            "grok_video_settings.json. Do not share that file with anyone.",
            xalign=0,
        )
        privacy_note.set_wrap(True)
        privacy_note.add_css_class("dim-label")
        content.append(privacy_note)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content.append(button_box)

        self.generate_button = Gtk.Button(label="Generate video")
        self.generate_button.add_css_class("suggested-action")
        self.generate_button.set_hexpand(True)
        self.generate_button.connect("clicked", self._generate)
        button_box.append(self.generate_button)

        save_button = Gtk.Button(label="Save settings")
        save_button.connect("clicked", self._save_button_clicked)
        button_box.append(save_button)

        open_button = Gtk.Button(label="Open folder")
        open_button.connect("clicked", self._open_folder)
        button_box.append(open_button)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.spinner = Gtk.Spinner()
        status_box.append(self.spinner)
        self.status_label = Gtk.Label(label="Ready.", xalign=0, selectable=True)
        self.status_label.set_wrap(True)
        self.status_label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.status_label.set_hexpand(True)
        status_box.append(self.status_label)
        content.append(status_box)

        hint = Gtk.Label(
            label="Generation can take several minutes. The app waits for the result "
            "and saves the MP4 to the selected folder automatically.",
            xalign=0,
        )
        hint.set_wrap(True)
        hint.add_css_class("dim-label")
        content.append(hint)

    @staticmethod
    def _field_label(text: str) -> Gtk.Label:
        label = Gtk.Label(xalign=0)
        label.set_markup(f"<b>{text}</b>")
        return label

    @staticmethod
    def _password_entry(tooltip: str) -> Gtk.PasswordEntry:
        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        entry.set_hexpand(True)
        entry.set_tooltip_text(tooltip)
        return entry

    def _apply_settings(self) -> None:
        self._updating_ui = True
        self.provider_combo.set_active_id(self.settings["provider"])
        self.mode_combo.set_active_id(self.settings["mode"])
        self.xai_api_entry.set_text(self.settings["api_key"])
        self.google_api_entry.set_text(self.settings["google_api_key"])
        self.image_entry.set_text(self.settings["image_path"])
        self.folder_entry.set_text(self.settings["output_dir"])
        self.audio_check.set_active(self.settings["generate_audio"])
        self._updating_ui = False
        self._refresh_provider_interface()

    def _on_provider_changed(self, _combo: Gtk.ComboBoxText) -> None:
        if self._updating_ui:
            return
        self._remember_current_options()
        self._refresh_provider_interface()

    def _on_model_changed(self, _combo: Gtk.ComboBoxText) -> None:
        if self._updating_ui:
            return
        model_id = self.model_combo.get_active_id()
        if model_id:
            self._provider_options[self._current_provider]["model"] = model_id
        self._update_resolution_options()

    def _on_mode_changed(self, _combo: Gtk.ComboBoxText) -> None:
        if not self._updating_ui:
            self._refresh_mode_interface()

    def _refresh_provider_interface(self) -> None:
        provider = self.provider_combo.get_active_id() or "grok"
        self._current_provider = provider
        options = self._provider_options[provider]
        self._updating_ui = True

        self.api_key_label.set_markup(
            f"<b>{'xAI API key' if provider == 'grok' else 'Google API key'}</b>"
        )
        self.api_stack.set_visible_child_name(provider)
        self.audio_stack.set_visible_child_name(provider)
        self._update_model_options(options["model"])
        self._update_aspect_options(options["aspect_ratio"])
        self._update_resolution_options(options["resolution"])

        minimum = 1 if provider == "grok" else 3
        self.duration_spin.set_range(minimum, 15)
        self.duration_spin.set_value(options["duration"])
        self.duration_spin.set_tooltip_text(f"{minimum} to 15 seconds")

        self._updating_ui = False
        self._refresh_mode_interface()

    def _refresh_mode_interface(self) -> None:
        image_mode = self.mode_combo.get_active_id() == "image"
        self.image_label.set_visible(image_mode)
        self.image_box.set_visible(image_mode)
        prompt_title = "Prompt — describe the image motion" if image_mode else "Prompt — describe the video"
        self.prompt_label.set_markup(f"<b>{prompt_title}</b>")
        automatic = image_mode and self._current_provider == "grok"
        self.aspect_stack.set_visible_child_name("automatic" if automatic else "choice")

    def _models_for_current_provider(self) -> dict:
        return VIDEO_MODELS if self._current_provider == "grok" else GOOGLE_VIDEO_MODELS

    def _update_model_options(self, preferred: str | None) -> None:
        models = self._models_for_current_provider()
        self.model_combo.remove_all()
        for model_id, model in models.items():
            self.model_combo.append(model_id, model["label"])
        if preferred not in models:
            preferred = next(iter(models))
        self.model_combo.set_active_id(preferred)

    def _update_aspect_options(self, preferred: str | None) -> None:
        ratios = ASPECT_RATIOS if self._current_provider == "grok" else GOOGLE_ASPECT_RATIOS
        self.aspect_combo.remove_all()
        for ratio in ratios:
            self.aspect_combo.append(ratio, ratio)
        if preferred not in ratios:
            preferred = "16:9"
        self.aspect_combo.set_active_id(preferred)

    def _update_resolution_options(self, preferred: str | None = None) -> None:
        if preferred is None:
            preferred = self.resolution_combo.get_active_id()
        model_id = self.model_combo.get_active_id()
        models = self._models_for_current_provider()
        if model_id not in models:
            return
        resolutions = models[model_id]["resolutions"]

        was_updating = self._updating_ui
        self._updating_ui = True
        self.resolution_combo.remove_all()
        for resolution in resolutions:
            label = "4K" if resolution == "4k" else resolution
            self.resolution_combo.append(resolution, label)
        if preferred not in resolutions:
            preferred = "720p" if "720p" in resolutions else resolutions[0]
        self.resolution_combo.set_active_id(preferred)
        self._updating_ui = was_updating

    def _remember_current_options(self) -> None:
        options = self._provider_options[self._current_provider]
        model = self.model_combo.get_active_id()
        aspect = self.aspect_combo.get_active_id()
        resolution = self.resolution_combo.get_active_id()
        if model:
            options["model"] = model
        if aspect:
            options["aspect_ratio"] = aspect
        if resolution:
            options["resolution"] = resolution
        options["duration"] = self.duration_spin.get_value_as_int()
        if self._current_provider == "grok":
            options["generate_audio"] = self.audio_check.get_active()

    def _collect_settings(self) -> dict:
        self._remember_current_options()
        settings = self.settings.copy()
        grok = self._provider_options["grok"]
        google = self._provider_options["google"]
        settings.update(
            {
                "provider": self._current_provider,
                "mode": self.mode_combo.get_active_id() or "text",
                "api_key": self.xai_api_entry.get_text().strip(),
                "google_api_key": self.google_api_entry.get_text().strip(),
                "model": grok["model"],
                "duration": grok["duration"],
                "aspect_ratio": grok["aspect_ratio"],
                "resolution": grok["resolution"],
                "generate_audio": grok["generate_audio"],
                "google_model": google["model"],
                "google_duration": google["duration"],
                "google_aspect_ratio": google["aspect_ratio"],
                "google_resolution": google["resolution"],
                "image_path": self.image_entry.get_text().strip(),
                "output_dir": self.folder_entry.get_text().strip(),
            }
        )
        return settings

    def _save_settings(self, show_confirmation: bool = True) -> bool:
        try:
            self.settings = self._collect_settings()
            self.settings_store.save(self.settings)
        except SettingsError as exc:
            self._show_error(str(exc))
            return False
        if show_confirmation:
            self.status_label.set_text("API keys and settings have been saved locally.")
        return True

    def _save_button_clicked(self, _button: Gtk.Button) -> None:
        self._save_settings()

    def _generate(self, _button: Gtk.Button) -> None:
        if self._is_generating:
            return

        buffer = self.prompt_view.get_buffer()
        prompt = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True).strip()
        settings = self._collect_settings()
        provider = settings["provider"]

        api_key = settings["api_key"] if provider == "grok" else settings["google_api_key"]
        if not api_key:
            key_name = "xAI" if provider == "grok" else "Google Gemini"
            self._show_error(f"Enter your {key_name} API key.")
            return
        if not prompt:
            self._show_error("Enter a prompt describing the video or the image motion.")
            return

        image_path = None
        if settings["mode"] == "image":
            try:
                image_path = self._get_image_path()
            except ValueError as exc:
                self._show_error(str(exc))
                return

        try:
            output_dir = self._get_output_folder(create=True)
        except ValueError as exc:
            self._show_error(str(exc))
            return

        self.folder_entry.set_text(str(output_dir))
        if not self._save_settings(show_confirmation=False):
            return

        if provider == "grok":
            client = GrokVideoClient(api_key)
            status = "Sending the request to Grok…"
        else:
            client = GoogleVideoClient(api_key)
            status = "Sending the request to Google Gemini…"

        self._set_generating(True)
        self.status_label.set_text(status)
        worker = threading.Thread(
            target=self._run_generation,
            args=(provider, client, prompt, settings, output_dir, image_path),
            daemon=True,
            name=f"{provider}-video-generation",
        )
        worker.start()

    def _run_generation(
        self,
        provider: str,
        client: GrokVideoClient | GoogleVideoClient,
        prompt: str,
        settings: dict,
        output_dir: Path,
        image_path: Path | None,
    ) -> None:
        try:
            if provider == "grok":
                assert isinstance(client, GrokVideoClient)
                request_id = client.create_video(
                    prompt=prompt,
                    model=settings["model"],
                    duration=settings["duration"],
                    aspect_ratio=settings["aspect_ratio"],
                    resolution=settings["resolution"],
                    generate_audio=settings["generate_audio"],
                    image_path=image_path,
                )
                self._notify_status(f"Request sent. ID: {request_id}\nWaiting for the video…")
                video_url = client.wait_for_video(
                    request_id,
                    progress_callback=self._notify_status,
                )
                self._notify_status("The video is ready. Downloading the MP4…")
                target = make_video_path(output_dir, request_id, prefix="grok")
                saved_path = client.download_video(video_url, target)
            else:
                assert isinstance(client, GoogleVideoClient)
                interaction_id, video_bytes = client.generate_video(
                    prompt=prompt,
                    model=settings["google_model"],
                    duration=settings["google_duration"],
                    aspect_ratio=settings["google_aspect_ratio"],
                    resolution=settings["google_resolution"],
                    image_path=image_path,
                )
                self._notify_status("Google generated the video. Saving the MP4…")
                target = make_video_path(output_dir, interaction_id, prefix="google")
                saved_path = client.save_video(video_bytes, target)
        except (GrokAPIError, GoogleAPIError, ImageInputError, OSError) as exc:
            GLib.idle_add(self._generation_failed, str(exc))
        except Exception as exc:
            GLib.idle_add(self._generation_failed, f"Unexpected error: {exc}")
        else:
            GLib.idle_add(self._generation_succeeded, str(saved_path))

    def _notify_status(self, message: str) -> None:
        if not self._closing:
            GLib.idle_add(self._apply_running_status, message)

    def _apply_running_status(self, message: str) -> bool:
        if self._is_generating and not self._closing:
            self.status_label.set_text(message)
        return False

    def _generation_succeeded(self, saved_path: str) -> bool:
        if self._closing:
            return False
        self._set_generating(False)
        self.status_label.set_text(f"Video saved:\n{saved_path}")
        return False

    def _generation_failed(self, message: str) -> bool:
        if self._closing:
            return False
        self._set_generating(False)
        self.status_label.set_text(f"Error: {message}")
        self._show_error(message)
        return False

    def _set_generating(self, generating: bool) -> None:
        self._is_generating = generating
        self.generate_button.set_sensitive(not generating)
        self.options_grid.set_sensitive(not generating)
        self.prompt_view.set_sensitive(not generating)
        if generating:
            self.spinner.start()
        else:
            self.spinner.stop()

    def _get_image_path(self) -> Path:
        raw_path = self.image_entry.get_text().strip()
        if not raw_path:
            raise ValueError("Choose a source image for image-to-video generation.")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.is_file():
            raise ValueError(f"The selected image does not exist: {path}")
        return path.resolve()

    def _get_output_folder(self, create: bool) -> Path:
        raw_path = self.folder_entry.get_text().strip()
        if not raw_path:
            raise ValueError("Choose a folder where the video will be saved.")
        folder = Path(raw_path).expanduser()
        if not folder.is_absolute():
            folder = Path.cwd() / folder
        try:
            if create:
                folder.mkdir(parents=True, exist_ok=True)
            if create and not folder.is_dir():
                raise ValueError("The selected path is not a folder.")
        except OSError as exc:
            raise ValueError(f"The video folder is not accessible: {exc}") from exc
        return folder.resolve()

    def _choose_image(self, _button: Gtk.Button) -> None:
        if self._image_dialog is not None:
            return
        dialog = Gtk.FileChooserNative.new(
            "Choose a source image",
            self,
            Gtk.FileChooserAction.OPEN,
            "Choose",
            "Cancel",
        )
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Images (PNG, JPEG, WebP)")
        for mime_type in ("image/png", "image/jpeg", "image/webp"):
            image_filter.add_mime_type(mime_type)
        dialog.add_filter(image_filter)

        current = Path(self.image_entry.get_text().strip() or str(Path.cwd())).expanduser()
        folder = current.parent if current.is_file() else current
        if folder.exists():
            dialog.set_current_folder(Gio.File.new_for_path(str(folder)))
        dialog.connect("response", self._image_selected)
        self._image_dialog = dialog
        dialog.show()

    def _image_selected(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            selected = dialog.get_file()
            if selected is not None:
                path = selected.get_path()
                if path:
                    self.image_entry.set_text(path)
        self._image_dialog = None
        dialog.destroy()

    def _choose_folder(self, _button: Gtk.Button) -> None:
        if self._folder_dialog is not None:
            return
        dialog = Gtk.FileChooserNative.new(
            "Choose a folder for the video",
            self,
            Gtk.FileChooserAction.SELECT_FOLDER,
            "Choose",
            "Cancel",
        )
        current = Path(self.folder_entry.get_text().strip() or str(Path.cwd())).expanduser()
        if current.exists():
            dialog.set_current_folder(Gio.File.new_for_path(str(current)))
        dialog.connect("response", self._folder_selected)
        self._folder_dialog = dialog
        dialog.show()

    def _folder_selected(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            selected = dialog.get_file()
            if selected is not None:
                path = selected.get_path()
                if path:
                    self.folder_entry.set_text(path)
        self._folder_dialog = None
        dialog.destroy()

    def _open_folder(self, _button: Gtk.Button) -> None:
        try:
            folder = self._get_output_folder(create=True)
            uri = Gio.File.new_for_path(str(folder)).get_uri()
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except (ValueError, GLib.Error) as exc:
            self._show_error(f"Could not open the folder: {exc}")

    def _show_error(self, message: str) -> None:
        if self._closing:
            return
        dialog = Adw.AlertDialog(heading="AI Video Maker", body=message)
        dialog.add_response("close", "Close")
        dialog.set_close_response("close")
        dialog.present(self)

    def _on_close_request(self, _window: Adw.ApplicationWindow) -> bool:
        self._closing = True
        try:
            self.settings_store.save(self._collect_settings())
        except SettingsError:
            pass
        return False


class VideoMakerApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="local.grok.VideoMaker")

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = VideoMakerWindow(self)
        window.present()


def main() -> int:
    application = VideoMakerApplication()
    return application.run([])


if __name__ == "__main__":
    raise SystemExit(main())
