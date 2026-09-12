from __future__ import annotations

import json
import subprocess
import sys
import threading
from typing import List

from . import folders, history, notify
from .config import Config
from .serve import serve_in_thread
from .watcher import Watcher

NOTIFY_EVENTS = {"phase-changed", "blocked", "pending-answers"}


def _icon_color(projects) -> str:
    statuses = [project.status for project in projects]
    if "blocked" in statuses:
        return "#d33"
    if any(project.pending_answers for project in projects):
        return "#e0a800"
    if any((project.git or {}).get("dirty") for project in projects):
        return "#e0a800"
    return "#2a2"


def _make_image(draw_module, image_module, color: str):
    image = image_module.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = draw_module.Draw(image)
    draw.ellipse((4, 4, 60, 60), fill=color)
    return image


def _tooltip(projects) -> str:
    total_done = sum(project.tasks_done for project in projects)
    total = sum(project.tasks_total for project in projects)
    return f"{len(projects)} projects · {total_done}/{total} tasks"


def _reveal(path: str) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", path])
    except OSError:
        pass


def _open_folder(path: str) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", path])
    except OSError:
        pass


def _copy(text: str) -> None:
    command = ["pbcopy"] if sys.platform == "darwin" else ["clip"]
    try:
        subprocess.run(command, input=text, text=True, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def run(config: Config = None, config_path=None, serve_port=None) -> None:
    import pystray
    from PIL import Image, ImageDraw

    config = config or Config.load(config_path)
    watcher = Watcher(config)
    paused = {"value": False}
    stop_event = threading.Event()
    server = None

    def make_image(color: str):
        return _make_image(ImageDraw, Image, color)

    def on_events(events: List[dict]) -> None:
        for event in events:
            if config.history:
                history.append_event(event)
            if event.get("type") in NOTIFY_EVENTS:
                notify.notify("gsd-path", str(event.get("detail", "")), enabled=config.notify)
        refresh()

    def poll_loop() -> None:
        while not stop_event.is_set():
            if paused["value"]:
                stop_event.wait(config.poll_seconds)
                continue
            events = watcher.poll_once()
            if events:
                on_events(events)
            stop_event.wait(config.poll_seconds)

    def project_menu(project):
        git = project.git or {}
        branch = git.get("branch") or project.branch or "-"
        dirty = git.get("dirty")
        if dirty is True:
            branch += " (dirty)"
        elif dirty is False:
            branch += " (clean)"
        wave = ""
        if project.current_wave is not None:
            wave = f" — Wave {project.current_wave}"
        label = project.project or project.root
        if project.milestone:
            label = f"{label} — {project.milestone}"
        return pystray.MenuItem(
            label,
            pystray.Menu(
                pystray.MenuItem(f"Phase: {project.phase} ({project.status})", None, enabled=False),
                pystray.MenuItem(f"Tasks: {project.tasks_done}/{project.tasks_total} done{wave}", None, enabled=False),
                pystray.MenuItem(f"Branch: {branch}", None, enabled=False),
                pystray.MenuItem(f"Pending answers: {len(project.pending_answers)}", None, enabled=False),
                pystray.MenuItem(f"Next skill: {project.next_skill or '-'}", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Reveal in Finder/Explorer", lambda icon, item, p=project.root: _reveal(p)),
                pystray.MenuItem(
                    "Copy status JSON",
                    lambda icon, item, p=project: _copy(json.dumps(p.to_dict(), indent=2, sort_keys=True)),
                ),
                pystray.MenuItem(
                    "Open .project folder",
                    lambda icon, item, p=project.root: _open_folder(p + "/.project"),
                ),
            ),
        )

    def watched_folders_menu():
        return pystray.Menu(
            *[
                pystray.MenuItem(
                    parent,
                    pystray.Menu(
                        pystray.MenuItem("Remove", lambda icon, item, p=parent: remove_parent(p))
                    ),
                )
                for parent in config.parents
            ]
        ) if config.parents else pystray.Menu(pystray.MenuItem("(none)", None, enabled=False))

    def add_folder(icon, item) -> None:
        picked = folders.pick_folder()
        if picked:
            config.add_parent(picked)
            config.save(config_path)
            watcher.poll_once()
            refresh()

    def remove_parent(parent: str) -> None:
        config.remove_parent(parent)
        config.save(config_path)
        watcher.projects.pop(parent, None)
        refresh()

    def rescan(icon, item) -> None:
        watcher.poll_once()
        refresh()

    def toggle_pause(icon, item) -> None:
        paused["value"] = not paused["value"]

    def quit_app(icon, item) -> None:
        stop_event.set()
        icon.stop()

    def build_menu():
        projects = sorted(watcher.projects.values(), key=lambda p: p.root)
        items = [project_menu(project) for project in projects]
        items += [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Add watched folder…", add_folder),
            pystray.MenuItem("Watched folders", watched_folders_menu()),
            pystray.MenuItem("Rescan now", rescan),
            pystray.MenuItem(
                "Pause monitoring",
                toggle_pause,
                checked=lambda item: paused["value"],
            ),
            pystray.MenuItem("Quit", quit_app),
        ]
        return pystray.Menu(*items)

    def refresh() -> None:
        projects = list(watcher.projects.values())
        icon.icon = make_image(_icon_color(projects))
        icon.title = _tooltip(projects)
        icon.menu = build_menu()
        icon.update_menu()

    watcher.poll_once(scan_sessions=False)
    projects = list(watcher.projects.values())
    if serve_port is not None:
        server, _dashboard_thread = serve_in_thread(watcher, port=serve_port)
    icon = pystray.Icon(
        "gsd-path-daemon",
        make_image(_icon_color(projects)),
        _tooltip(projects),
        build_menu(),
    )
    thread = threading.Thread(target=poll_loop, daemon=True)
    thread.start()
    try:
        icon.run()
    finally:
        stop_event.set()
        if server is not None:
            server.shutdown()
            server.server_close()
