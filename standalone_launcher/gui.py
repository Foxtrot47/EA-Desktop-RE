"""Windows GUI for the standalone EA account and library implementation."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from custom_launcher.ea_custom_launcher import discover_installed_games
from standalone_launcher.library import (
    GraphQlClient,
    load_snapshot_dpapi,
    retrieve_library,
    save_snapshot_dpapi,
)
from standalone_launcher.login import load_tokens_dpapi
from standalone_launcher.managed_launch import BFN_CONTENT_ID, launch_game
from standalone_launcher.license import license_path
from standalone_launcher.license_service import LicenseRefreshResult, refresh_owned_license
from standalone_launcher.model import build_library_records, visible_owned_games
from standalone_launcher.reconcile import reconcile_library


ROOT = Path(__file__).resolve().parents[1]
TOKEN_STORE = ROOT / "private" / "ea_tokens.dpapi"
LIBRARY_STORE = ROOT / "private" / "ea_library.dpapi"


class StandaloneLibraryWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("EA Standalone Library")
        self.geometry("1080x650")
        self.minsize(820, 480)
        self.records = []
        self.displayed_records = []
        self._bfn_session = None
        self._closing = threading.Event()
        self.protocol("WM_DELETE_WINDOW", self._close_window)

        header = ttk.Frame(self, padding=(14, 12))
        header.pack(fill=tk.X)
        self.title_count = tk.StringVar(value="Loading library…")
        ttk.Label(header, textvariable=self.title_count, font=("Segoe UI", 18, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh from EA", command=self.refresh_online).pack(side=tk.RIGHT)
        ttk.Button(header, text="Reload snapshot", command=self.load_snapshot).pack(side=tk.RIGHT, padx=8)
        self.launch_button = ttk.Button(header, text="Launch selected", command=self.launch_selected)
        self.launch_button.pack(side=tk.RIGHT)
        self.renew_button = ttk.Button(header, text="Renew license", command=self.renew_selected_license)
        self.renew_button.pack(side=tk.RIGHT, padx=8)

        summary = ttk.Frame(self, padding=(14, 0, 14, 10))
        summary.pack(fill=tk.X)
        self.summary_text = tk.StringVar(value="")
        ttk.Label(summary, textvariable=self.summary_text).pack(side=tk.LEFT)
        self.show_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            summary,
            text="Show disabled products and add-ons",
            variable=self.show_all,
            command=self.populate,
        ).pack(side=tk.RIGHT)

        columns = ("title", "type", "status", "downloadable", "installed", "location", "offer")
        self.table = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        specs = (
            ("title", "Title", 250),
            ("type", "Type", 95),
            ("status", "Status", 85),
            ("downloadable", "Download", 75),
            ("installed", "Installed", 75),
            ("location", "Local path", 270),
            ("offer", "Offer ID", 190),
        )
        for key, label, width in specs:
            self.table.heading(key, text=label)
            self.table.column(key, width=width, stretch=key in {"title", "location"})
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<Double-1>", lambda _event: self.launch_selected())
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(14, 0), pady=(0, 14))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 14), pady=(0, 14))

        self.load_snapshot()

    def load_snapshot(self) -> None:
        try:
            snapshot = load_snapshot_dpapi(LIBRARY_STORE)
            self._apply_snapshot(snapshot)
        except Exception as exc:
            self.title_count.set("Library unavailable")
            self.summary_text.set(str(exc))

    def _apply_snapshot(self, snapshot) -> None:
        self.records = build_library_records(snapshot, discover_installed_games())
        reconciliation = reconcile_library(snapshot)
        active_titles = visible_owned_games(self.records)
        entitlements = snapshot.get("entitlements", [])
        catalog = snapshot.get("catalog", {})
        offers = catalog.get("legacyOffers", []) if isinstance(catalog, dict) else []
        products = catalog.get("gameProducts", []) if isinstance(catalog, dict) else []
        self.title_count.set(f"{len(active_titles)} EA-reconciled titles")
        self.summary_text.set(
            f"{len(entitlements)} entitlement records  •  "
            f"{reconciliation.active_entitlement_count} active  •  "
            f"{len(offers)} catalog offers  •  {len(products)} product records  •  "
            f"{sum(record.installed for record in active_titles)} active titles installed"
        )
        self.populate()

    def populate(self) -> None:
        self.table.delete(*self.table.get_children())
        self.displayed_records = self.records if self.show_all.get() else visible_owned_games(self.records)
        for index, record in enumerate(self.displayed_records):
            self.table.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    record.title.strip(),
                    record.display_type or "",
                    "SUPPRESSED" if record.suppressed else ", ".join(record.entitlement_statuses),
                    "Yes" if record.downloadable else "No",
                    "Yes" if record.installed else "No",
                    record.install_location or "",
                    record.offer_id,
                ),
            )

    def _selected_record(self):
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo("EA Standalone Library", "Select a title first.")
            return None
        return self.displayed_records[int(selection[0])]

    def launch_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        if not record.installed or not record.install_location:
            messagebox.showinfo("EA Standalone Library", f"{record.title} is not installed.")
            return
        if record.offer_id == "Origin.OFR.50.0004873" and self._bfn_session is not None and self._bfn_session.poll() is None:
            messagebox.showinfo("EA Standalone Library", "BFN already has an active standalone session.")
            return
        if record.offer_id == "Origin.OFR.50.0000357" and not license_path("1019521").exists():
            self._start_renewal(record.offer_id, launch_location=record.install_location)
            return
        self._launch_location(record.install_location)

    def _launch_location(self, location: str) -> None:
        self.summary_text.set("Starting standalone game session…")
        self.launch_button.state(["disabled"])
        self.renew_button.state(["disabled"])
        threading.Thread(target=self._launch_worker, args=(location,), daemon=True).start()

    def _post_launch(self, callback, *args) -> None:
        if self._closing.is_set():
            return
        try:
            self.after(0, callback, *args)
        except RuntimeError:
            if not self._closing.is_set():
                raise

    def _launch_worker(self, location: str) -> None:
        try:
            launcher, process = launch_game(location)
        except Exception as exc:
            self._post_launch(self._launch_failed, exc)
            return
        self._post_launch(self._launch_finished, launcher, process)

    def _launch_finished(self, launcher, process) -> None:
        self.launch_button.state(["!disabled"])
        self.renew_button.state(["!disabled"])
        if launcher.content_id == BFN_CONTENT_ID:
            self._bfn_session = process
            self.summary_text.set(f"Started BFN standalone session (PID {process.pid}); helpers stay until the game exits")
            threading.Thread(target=self._watch_bfn_session, args=(process,), daemon=True).start()
            return
        self.summary_text.set(f"Started {launcher.name} (PID {process.pid}) directly from the installed DiP manifest")

    def _launch_failed(self, exc: Exception) -> None:
        self.launch_button.state(["!disabled"])
        self.renew_button.state(["!disabled"])
        self.summary_text.set("Game launch failed")
        messagebox.showerror("EA Standalone Library", str(exc))

    def _watch_bfn_session(self, process) -> None:
        code = process.wait()
        self._post_launch(self._bfn_finished, process, code)

    def _bfn_finished(self, process, code: int) -> None:
        if self._bfn_session is not process:
            return
        self._bfn_session = None
        self.summary_text.set("BFN session ended; compatibility helpers stopped")
        if code:
            messagebox.showerror("EA Standalone Library", "BFN's standalone session failed. No game process was forcibly closed.")

    def _close_window(self) -> None:
        # The independent supervisor, not this window, owns the running session.
        self._closing.set()
        self.destroy()

    def renew_selected_license(self) -> None:
        record = self._selected_record()
        if record is not None:
            self._start_renewal(record.offer_id)

    def _start_renewal(self, offer_id: str, *, launch_location: str | None = None) -> None:
        self.summary_text.set("Requesting an EA-signed license through the standalone session…")
        self.launch_button.state(["disabled"])
        self.renew_button.state(["disabled"])
        threading.Thread(
            target=self._renew_worker, args=(offer_id, launch_location), daemon=True
        ).start()

    def _renew_worker(self, offer_id: str, launch_location: str | None) -> None:
        try:
            result = refresh_owned_license(offer_id)
            self.after(0, self._renew_finished, result, launch_location)
        except Exception as exc:
            self.after(0, self._renew_failed, exc)

    def _renew_finished(self, result: LicenseRefreshResult, launch_location: str | None) -> None:
        self.launch_button.state(["!disabled"])
        self.renew_button.state(["!disabled"])
        self.summary_text.set(f"EA-signed license installed for {result.offer_id}")
        if launch_location is not None:
            self._launch_location(launch_location)

    def _renew_failed(self, exc: Exception) -> None:
        self.launch_button.state(["!disabled"])
        self.renew_button.state(["!disabled"])
        self.summary_text.set("License request failed")
        messagebox.showerror("EA Standalone Library", str(exc))

    def refresh_online(self) -> None:
        self.title_count.set("Refreshing from EA…")
        self.summary_text.set("Using the DPAPI-protected standalone OAuth session")
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        try:
            tokens = load_tokens_dpapi(TOKEN_STORE)
            snapshot = retrieve_library(GraphQlClient(tokens.access_token))
            save_snapshot_dpapi(LIBRARY_STORE, snapshot)
            self.after(0, self._apply_snapshot, snapshot)
        except Exception as exc:
            self.after(0, self._refresh_failed, exc)

    def _refresh_failed(self, exc: Exception) -> None:
        self.title_count.set("Refresh failed")
        messagebox.showerror("EA Standalone Library", str(exc))
        self.load_snapshot()


def main() -> None:
    StandaloneLibraryWindow().mainloop()


if __name__ == "__main__":
    main()
