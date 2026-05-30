import os
import re
import sys
import threading
import requests
import customtkinter as ctk
from PIL import Image
from tkinter import filedialog, messagebox
from urllib.parse import urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed


APP_NAME = "Plex Video Downloader"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    )
}


def safe_filename(name):
    return re.sub(r'[<>:"/\\|?*]', "", name).strip()


def extract_episode_number(filename):
    patterns = [
        r"\bS\d{1,2}E(\d{1,3})\b",
        r"\bEpisode\s*(\d{1,3})\b",
        r"\bEp\s*(\d{1,3})\b",
        r"[_\-\s](\d{1,3})[_\-\s]",
        r"\b(\d{1,3})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            return int(match.group(1))

    return None


def get_original_filename(url):
    filename = unquote(os.path.basename(urlparse(url).path))
    return filename or "video.mp4"


class PlexDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(APP_NAME)
        self.geometry("1150x850")
        self.minsize(950, 720)

        try:
            import ctypes
            myappid = "plexvideodownloader.v1"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

            self.iconbitmap(resource_path("downloadicon.ico"))
        except Exception as e:
            print("Icon load failed:", e)

        self.mode = ctk.StringVar(value="show")
        self.output_folder = ctk.StringVar(value=os.path.expanduser("~/Downloads"))
        self.show_name = ctk.StringVar()
        self.season_number = ctk.StringVar(value="1")
        self.movie_name = ctk.StringVar()
        self.movie_year = ctk.StringVar()
        self.workers = ctk.StringVar(value="3")
        self.chunk_size = ctk.StringVar(value="16")

        self.is_downloading = False
        self.queue_rows = {}

        self.cancel_event = threading.Event()

        self.build_ui()

    def build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)
        self.grid_rowconfigure(7, weight=1)

        try:
            self.logo_image = ctk.CTkImage(
                light_image=Image.open(resource_path("downloadicon.png")),
                dark_image=Image.open(resource_path("downloadicon.png")),
                size=(115, 115)
            )
            logo = ctk.CTkLabel(self, image=self.logo_image, text="")
            logo.grid(row=0, column=0, padx=20, pady=(12, 0))
        except Exception:
            pass

        title = ctk.CTkLabel(
            self,
            text="Plex Video Downloader",
            font=("Segoe UI", 30, "bold")
        )
        title.grid(row=1, column=0, padx=20, pady=(5, 10))

        self.mode_frame = ctk.CTkFrame(self)
        self.mode_frame.grid(row=2, column=0, padx=20, pady=8, sticky="ew")
        self.mode_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkRadioButton(
            self.mode_frame,
            text="TV Show / Anime",
            variable=self.mode,
            value="show",
            command=self.update_mode
        ).grid(row=0, column=0, padx=20, pady=12, sticky="w")

        ctk.CTkRadioButton(
            self.mode_frame,
            text="Movie",
            variable=self.mode,
            value="movie",
            command=self.update_mode
        ).grid(row=0, column=1, padx=20, pady=12, sticky="w")

        self.details_frame = ctk.CTkFrame(self)
        self.details_frame.grid(row=3, column=0, padx=20, pady=8, sticky="ew")
        self.details_frame.grid_columnconfigure(1, weight=1)

        self.show_name_label = ctk.CTkLabel(self.details_frame, text="Show Name:")
        self.show_name_entry = ctk.CTkEntry(
            self.details_frame,
            textvariable=self.show_name,
            placeholder_text="Example: Dr. Stone"
        )

        self.season_label = ctk.CTkLabel(self.details_frame, text="Season:")
        self.season_entry = ctk.CTkEntry(
            self.details_frame,
            textvariable=self.season_number,
            width=80
        )

        self.movie_name_label = ctk.CTkLabel(self.details_frame, text="Movie Name:")
        self.movie_name_entry = ctk.CTkEntry(
            self.details_frame,
            textvariable=self.movie_name,
            placeholder_text="Example: Spirited Away"
        )

        self.movie_year_label = ctk.CTkLabel(self.details_frame, text="Year:")
        self.movie_year_entry = ctk.CTkEntry(
            self.details_frame,
            textvariable=self.movie_year,
            width=100,
            placeholder_text="2001"
        )

        self.output_frame = ctk.CTkFrame(self)
        self.output_frame.grid(row=4, column=0, padx=20, pady=8, sticky="ew")
        self.output_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.output_frame, text="Output Folder:").grid(
            row=0, column=0, padx=15, pady=12, sticky="w"
        )

        ctk.CTkEntry(
            self.output_frame,
            textvariable=self.output_folder
        ).grid(row=0, column=1, padx=10, pady=12, sticky="ew")

        ctk.CTkButton(
            self.output_frame,
            text="Browse",
            width=100,
            command=self.browse_output
        ).grid(row=0, column=2, padx=15, pady=12)

        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=5, column=0, padx=20, pady=8, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self.main_frame,
            text="Paste Direct Video Links",
            font=("Segoe UI", 15, "bold")
        ).grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")

        self.links_box = ctk.CTkTextbox(self.main_frame, height=170)
        self.links_box.grid(row=1, column=0, padx=15, pady=10, sticky="nsew")

        self.settings_frame = ctk.CTkFrame(self.main_frame)
        self.settings_frame.grid(row=2, column=0, padx=15, pady=10, sticky="ew")
        self.settings_frame.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(
            self.settings_frame,
            text="Workers:"
        ).grid(row=0, column=0, padx=15, pady=12, sticky="w")

        ctk.CTkEntry(
            self.settings_frame,
            textvariable=self.workers,
            width=80
        ).grid(row=0, column=1, padx=10, pady=12, sticky="w")

        ctk.CTkLabel(
            self.settings_frame,
            text="Chunk Size MB:"
        ).grid(row=0, column=2, padx=15, pady=12, sticky="w")

        ctk.CTkEntry(
            self.settings_frame,
            textvariable=self.chunk_size,
            width=80
        ).grid(row=0, column=3, padx=10, pady=12, sticky="w")

        self.overall_progress = ctk.CTkProgressBar(self.main_frame)
        self.overall_progress.grid(row=3, column=0, padx=15, pady=(8, 3), sticky="ew")
        self.overall_progress.set(0)

        self.status_label = ctk.CTkLabel(self.main_frame, text="Ready")
        self.status_label.grid(row=4, column=0, padx=15, pady=(0, 10), sticky="w")

        self.controls_frame = ctk.CTkFrame(self)
        self.controls_frame.grid(row=6, column=0, padx=20, pady=8, sticky="ew")
        self.controls_frame.grid_columnconfigure((0, 1, 2), weight=1)
        self.start_button = ctk.CTkButton(
            self.controls_frame,
            text="Start Download",
            height=42,
            command=self.start_download
        )
        self.start_button.grid(row=0, column=0, padx=10, pady=12, sticky="ew")

        self.clear_button = ctk.CTkButton(
            self.controls_frame,
            text="Clear Links",
            height=42,
            fg_color="gray",
            command=self.clear_links
        )
        self.clear_button.grid(row=0, column=1, padx=10, pady=12, sticky="ew")

        self.stop_button = ctk.CTkButton(
            self.controls_frame,
            text="Stop Downloads",
            height=42,
            fg_color="#B22222",
            hover_color="#8B0000",
            command=self.stop_downloads
        )
        self.stop_button.grid(row=0, column=2, padx=10, pady=12, sticky="ew")

        self.queue_frame = ctk.CTkFrame(self)
        self.queue_frame.grid(row=7, column=0, padx=20, pady=(8, 20), sticky="nsew")
        self.queue_frame.grid_columnconfigure(0, weight=1)
        self.queue_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self.queue_frame,
            text="Download Queue",
            font=("Segoe UI", 15, "bold")
        ).grid(row=0, column=0, padx=15, pady=(12, 5), sticky="w")

        self.queue_scroll = ctk.CTkScrollableFrame(self.queue_frame)
        self.queue_scroll.grid(row=1, column=0, padx=15, pady=(5, 15), sticky="nsew")
        self.queue_scroll.grid_columnconfigure(0, weight=1)

        self.update_mode()

    def update_mode(self):
        for widget in self.details_frame.winfo_children():
            widget.grid_forget()

        if self.mode.get() == "show":
            self.show_name_label.grid(row=0, column=0, padx=15, pady=12, sticky="w")
            self.show_name_entry.grid(row=0, column=1, padx=10, pady=12, sticky="ew")
            self.season_label.grid(row=0, column=2, padx=15, pady=12, sticky="w")
            self.season_entry.grid(row=0, column=3, padx=10, pady=12, sticky="w")
        else:
            self.movie_name_label.grid(row=0, column=0, padx=15, pady=12, sticky="w")
            self.movie_name_entry.grid(row=0, column=1, padx=10, pady=12, sticky="ew")
            self.movie_year_label.grid(row=0, column=2, padx=15, pady=12, sticky="w")
            self.movie_year_entry.grid(row=0, column=3, padx=10, pady=12, sticky="w")

    def browse_output(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder.set(folder)

    def clear_links(self):
        if self.is_downloading:
            messagebox.showinfo("Download Running", "Wait for downloads to finish before clearing links.")
            return

        self.links_box.delete("1.0", "end")
        self.clear_queue()

    def stop_downloads(self):
        if not self.is_downloading:
            messagebox.showinfo("No Downloads Running", "There are no active downloads to stop.")
            return

        self.cancel_event.set()
        self.set_status("Stopping downloads...")
        self.stop_button.configure(state="disabled", text="Stopping...")

    def clear_queue(self):
        for widget in self.queue_scroll.winfo_children():
            widget.destroy()
        self.queue_rows.clear()

    def set_status(self, message):
        self.after(0, lambda: self.status_label.configure(text=message))

    def set_overall_progress(self, value):
        self.after(0, lambda: self.overall_progress.set(value))

    def validate(self):
        links = [
            line.strip()
            for line in self.links_box.get("1.0", "end").splitlines()
            if line.strip() and not line.lower().startswith("download")
        ]

        if not links:
            messagebox.showerror("Missing Links", "Paste at least one direct video link.")
            return None

        if self.mode.get() == "show":
            if not self.show_name.get().strip():
                messagebox.showerror("Missing Show Name", "Enter a show name.")
                return None

            if not self.season_number.get().isdigit():
                messagebox.showerror("Invalid Season", "Season must be a number.")
                return None

        if self.mode.get() == "movie":
            if not self.movie_name.get().strip():
                messagebox.showerror("Missing Movie Name", "Enter a movie name.")
                return None

        if not self.workers.get().isdigit():
            messagebox.showerror("Invalid Workers", "Workers must be a number.")
            return None

        if not self.chunk_size.get().isdigit():
            messagebox.showerror("Invalid Chunk Size", "Chunk size must be a number.")
            return None

        return links

    def build_filename(self, url, index):
        original = get_original_filename(url)
        ext = os.path.splitext(original)[1] or ".mp4"

        if self.mode.get() == "show":
            episode = extract_episode_number(original)

            if episode is None:
                episode = index + 1

            return safe_filename(
                f"{self.show_name.get().strip()} - S{int(self.season_number.get()):02d}E{episode:02d}{ext}"
            )

        movie_title = self.movie_name.get().strip()

        if self.movie_year.get().strip():
            movie_title = f"{movie_title} ({self.movie_year.get().strip()})"

        if index > 0:
            movie_title = f"{movie_title} Part {index + 1}"

        return safe_filename(f"{movie_title}{ext}")

    def create_queue_row(self, index, filename):
        row = ctk.CTkFrame(self.queue_scroll)
        row.grid(row=index, column=0, padx=5, pady=5, sticky="ew")
        row.grid_columnconfigure(0, weight=3)
        row.grid_columnconfigure(1, weight=1)
        row.grid_columnconfigure(2, weight=2)

        name_label = ctk.CTkLabel(row, text=filename, anchor="w")
        name_label.grid(row=0, column=0, padx=10, pady=8, sticky="ew")

        percent_label = ctk.CTkLabel(row, text="0%", width=60)
        percent_label.grid(row=0, column=1, padx=10, pady=8)

        progress = ctk.CTkProgressBar(row)
        progress.grid(row=0, column=2, padx=10, pady=8, sticky="ew")
        progress.set(0)

        self.queue_rows[index] = {
            "name": name_label,
            "percent": percent_label,
            "progress": progress
        }

    def update_queue_progress(self, index, percent, status_text=None):
        def update():
            row = self.queue_rows.get(index)
            if not row:
                return

            row["progress"].set(percent / 100)
            row["percent"].configure(text=f"{percent}%")

            if status_text:
                row["name"].configure(text=status_text)

        self.after(0, update)

    def start_download(self):
        if self.is_downloading:
            messagebox.showinfo("Already Running", "Downloads are already running.")
            return

        links = self.validate()

        if not links:
            return

        self.is_downloading = True
        self.cancel_event.clear()
        self.start_button.configure(state="disabled", text="Downloading...")
        self.clear_button.configure(state="disabled")
        self.stop_button.configure(state="normal", text="Stop Downloads")
        self.overall_progress.set(0)
        self.clear_queue()

        for index, url in enumerate(links):
            self.create_queue_row(index, self.build_filename(url, index))

        thread = threading.Thread(target=self.download_all, args=(links,), daemon=True)
        thread.start()

    def download_all(self, links):
        output_dir = self.output_folder.get()
        os.makedirs(output_dir, exist_ok=True)

        total = len(links)
        completed = 0

        max_workers = int(self.workers.get())
        chunk_bytes = int(self.chunk_size.get()) * 1024 * 1024

        self.set_status(f"Starting {total} download(s)...")

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self.download_one,
                        url,
                        index,
                        output_dir,
                        chunk_bytes
                    ): index
                    for index, url in enumerate(links)
                }

                for future in as_completed(futures):
                    index = futures[future]
                    completed += 1

                    try:
                        future.result()
                    except Exception as e:
                        filename = self.build_filename(links[index], index)
                        if "cancelled" in str(e).lower():
                            self.update_queue_progress(index, 0, f"CANCELLED: {filename}")
                        else:
                            self.update_queue_progress(index, 0, f"FAILED: {filename}")
                        print(e)

                    self.set_overall_progress(completed / total)
                    self.set_status(f"{completed}/{total} complete")

        finally:
            self.is_downloading = False
            self.after(0, lambda: self.start_button.configure(state="normal", text="Start Download"))
            self.after(0, lambda: self.clear_button.configure(state="normal"))
            self.after(0, lambda: self.stop_button.configure(state="normal", text="Stop Downloads"))

            if self.cancel_event.is_set():
                self.set_status("Stopped")
            else:
                self.set_status("Done")

    def download_one(self, url, index, output_dir, chunk_bytes):
        if self.cancel_event.is_set():
            raise Exception("Download cancelled")

        filename = self.build_filename(url, index)
        output_path = os.path.join(output_dir, filename)
        temp_path = output_path + ".part"

        if os.path.exists(output_path):
            self.update_queue_progress(index, 100, f"SKIPPED: {filename}")
            return

        session = requests.Session()
        session.headers.update(HEADERS)

        self.update_queue_progress(index, 0, f"Downloading: {filename}")

        try:
            with session.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(temp_path, "wb") as file:
                    for chunk in response.iter_content(chunk_size=chunk_bytes):
                        if self.cancel_event.is_set():
                            raise Exception("Download cancelled")

                        if chunk:
                            file.write(chunk)
                            downloaded += len(chunk)

                            if total_size > 0:
                                percent = int((downloaded / total_size) * 100)
                                self.update_queue_progress(index, min(percent, 99))

                    file.flush()
                    os.fsync(file.fileno())

            os.replace(temp_path, output_path)
            self.update_queue_progress(index, 100, f"SAVED: {filename}")

        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise


if __name__ == "__main__":
    app = PlexDownloaderApp()
    app.mainloop()