#!/usr/bin/env python3
"""Small Windows UI for the brokered EA custom-launcher prototype."""

from __future__ import annotations

import argparse
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ea_custom_launcher import (
    DEFAULT_LIBRARY_CONFIG,
    build_origin2_uri,
    execute_uri,
    launch_activity,
    library_games,
    save_library_mapping,
    status,
)


class LauncherWindow(tk.Tk):
    def __init__(self, config_path: Path):
        super().__init__()
        self.config_path = config_path
        self.games = []
        self.title("EA Custom Launcher")
        self.geometry("980x560")
        self.minsize(780, 430)

        toolbar = ttk.Frame(self, padding=10)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Open EA library / Sign in", command=self.open_library).pack(
            side=tk.LEFT, padx=8
        )
        self.status_text = tk.StringVar(value="Checking EA services…")
        ttk.Label(toolbar, textvariable=self.status_text).pack(side=tk.RIGHT)

        columns = ("name", "version", "identity", "path", "source")
        self.table = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        for column, title, width in (
            ("name", "Game", 220),
            ("version", "Version", 100),
            ("identity", "EA identity", 220),
            ("path", "Install path", 290),
            ("source", "Source", 130),
        ):
            self.table.heading(column, text=title)
            self.table.column(column, width=width, stretch=column in {"name", "path"})
        self.table.pack(fill=tk.BOTH, expand=True, padx=10)
        self.table.bind("<<TreeviewSelect>>", self.selection_changed)
        self.table.bind("<Double-1>", lambda _event: self.launch_selected())

        editor = ttk.LabelFrame(self, text="Selected game mapping", padding=10)
        editor.pack(fill=tk.X, padx=10, pady=10)
        self.name_var = tk.StringVar()
        self.path_var = tk.StringVar()
        self.context_var = tk.StringVar(value="OFFER")
        self.id_var = tk.StringVar()
        self.params_var = tk.StringVar()
        fields = (
            ("Name", self.name_var, 18),
            ("Install path", self.path_var, 35),
            ("Context", self.context_var, 12),
            ("EA ID", self.id_var, 25),
            ("Arguments", self.params_var, 22),
        )
        for index, (label, variable, width) in enumerate(fields):
            ttk.Label(editor, text=label).grid(row=0, column=index, sticky="w", padx=(0, 6))
            if label == "Context":
                widget = ttk.Combobox(
                    editor,
                    textvariable=variable,
                    values=("OFFER", "SLUG", "MASTERTITLE"),
                    width=width,
                    state="readonly",
                )
            else:
                widget = ttk.Entry(editor, textvariable=variable, width=width)
            widget.grid(row=1, column=index, sticky="ew", padx=(0, 6))
            editor.columnconfigure(index, weight=2 if label in {"Name", "Install path"} else 1)
        ttk.Button(editor, text="Save mapping", command=self.save_mapping).grid(row=1, column=5, padx=4)
        ttk.Button(editor, text="Launch", command=self.launch_selected).grid(row=1, column=6, padx=4)

        self.refresh()
        self.after(2000, self.poll_activity)

    def refresh(self) -> None:
        self.status_text.set("Refreshing…")
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        try:
            games = library_games(self.config_path)
            component_status = status()
            self.after(0, self._apply_refresh, games, component_status, None)
        except Exception as exc:
            self.after(0, self._apply_refresh, [], {}, exc)

    def _apply_refresh(self, games, component_status, error) -> None:
        if error:
            self.status_text.set("Refresh failed")
            messagebox.showerror("EA Custom Launcher", str(error))
            return
        self.games = games
        self.table.delete(*self.table.get_children())
        for index, game in enumerate(games):
            identity = f"{game.launch_context}:{game.launch_id}" if game.launch_id else "mapping required"
            self.table.insert(
                "",
                tk.END,
                iid=str(index),
                values=(game.name, game.version or "", identity, game.install_location, game.source),
            )
        processes = component_status.get("processes", {})
        ea_state = (
            "EA broker running"
            if processes.get("EADesktop.exe")
            else "EA broker will start silently on launch"
        )
        self.status_text.set(f"{len(games)} local games · {ea_state}")

    def selected_game(self):
        selected = self.table.selection()
        return self.games[int(selected[0])] if selected else None

    def selection_changed(self, _event=None) -> None:
        game = self.selected_game()
        if game is None:
            return
        self.name_var.set(game.name)
        self.path_var.set(game.install_location)
        self.context_var.set(game.launch_context or "OFFER")
        self.id_var.set(game.launch_id or game.offer_id or "")
        self.params_var.set(game.cmd_params or "")

    def save_mapping(self) -> None:
        if not self.name_var.get().strip() or not self.id_var.get().strip():
            messagebox.showwarning("EA Custom Launcher", "Name and EA ID are required.")
            return
        try:
            save_library_mapping(
                name=self.name_var.get().strip(),
                install_location=self.path_var.get().strip(),
                identifier=self.id_var.get().strip(),
                context=self.context_var.get(),
                cmd_params=self.params_var.get().strip() or None,
                path=self.config_path,
            )
            self.refresh()
        except Exception as exc:
            messagebox.showerror("EA Custom Launcher", str(exc))

    def launch_selected(self) -> None:
        identifier = self.id_var.get().strip()
        if not identifier:
            messagebox.showwarning("EA Custom Launcher", "Save an EA offer ID or slug for this game first.")
            return
        try:
            uri = build_origin2_uri(
                "game/launch",
                identifier=identifier,
                context_type=self.context_var.get(),
                cmd_params=self.params_var.get().strip() or None,
            )
            execute_uri(uri)
            self.status_text.set(f"Sent launch request for {self.name_var.get().strip()}")
        except Exception as exc:
            messagebox.showerror("EA Custom Launcher", str(exc))

    def poll_activity(self) -> None:
        game = self.selected_game()
        if game and game.launch_context == "OFFER" and game.launch_id:
            try:
                activity = launch_activity(game.launch_id)
                if activity.state not in {"never-observed", "no-log-data"}:
                    detail = activity.state.replace("-", " ")
                    if activity.exit_code is not None:
                        detail += f" · exit {activity.exit_code}"
                    self.status_text.set(f"{game.name}: {detail}")
            except Exception:
                pass
        self.after(2000, self.poll_activity)

    def open_library(self) -> None:
        try:
            execute_uri(build_origin2_uri("library/open"))
        except Exception as exc:
            messagebox.showerror("EA Custom Launcher", str(exc))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_LIBRARY_CONFIG)
    args = parser.parse_args()
    LauncherWindow(args.config).mainloop()


if __name__ == "__main__":
    main()
