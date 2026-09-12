from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .config import Config
from .discovery import scan
from .model import aggregate
from .probe import probe_project, utc_now_iso
from .serve import DEFAULT_PORT
from .watcher import Watcher


def _cmd_scan(config: Config) -> dict:
    roots = scan(config.parents, config.excludes, config.max_depth)
    projects = []
    for root in roots:
        status = probe_project(root, enrich=False)
        projects.append({
            "root": status.root,
            "project": status.project,
            "milestone": status.milestone,
            "phase": status.phase,
            "status": status.status,
        })
    return {"projects": projects}


def _cmd_dump(config: Config) -> dict:
    watcher = Watcher(config)
    watcher.poll_once()
    return aggregate(list(watcher.projects.values()), utc_now_iso())


def _plugin_scope(args) -> str:
    return "project" if getattr(args, "project_path", None) else "global"


def _cmd_plugin_status(manager, as_json: bool) -> int:
    detection = manager.detect_global()
    update = manager.check_update(fetch=False)
    payload = {
        "latest": update["latest"],
        "update_available": update["update_available"],
        "installed": update["installed"],
        "hosts": detection,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    for host, entry in detection.items():
        if entry["installed"]:
            manager.out(f"{host}: {entry['version'] or 'unknown version'} ({entry['root']})")
    if not update["installed"]:
        manager.out("no global gsd-path plugin installs detected")
    latest = update["latest"] or "unknown (no cached version check)"
    manager.out(f"latest: {latest}")
    manager.out("update available" if update["update_available"] else "up to date")
    return 0


def _cmd_plugin_run(label: str, result: dict, manager) -> int:
    manager.out(f"{label}: {'ok' if result['ok'] else 'failed'}")
    if result["stdout_tail"]:
        manager.out(result["stdout_tail"])
    if result["error"]:
        manager.out(f"error: {result['error']}")
    return 0 if result["ok"] else 1


def _cmd_plugin_uninstall(args, manager) -> int:
    if _plugin_scope(args) == "project":
        plan = manager.plan_uninstall_project(args.project_path)
        label = f"project {args.project_path}"
    else:
        plan = manager.plan_uninstall_global(args.hosts)
        label = "global roots"
    if args.dry_run or not args.yes:
        manager.out(f"uninstall plan for {label}:")
        for entry in plan["plan"]:
            manager.out(f"  remove [{entry['kind']}] {entry['path']} — {entry['reason']}")
        if not plan["plan"]:
            manager.out("  (nothing to remove)")
        for entry in plan["skipped"]:
            manager.out(f"  skip {entry['path']} — {entry['reason']}")
        if not args.yes and plan["plan"]:
            manager.out("dry-run only: re-run with --yes to apply")
        return 0
    result = manager.apply_plan(plan, confirm=True)
    for path in result["applied"]:
        manager.out(f"  removed {path}")
    for error in result["errors"]:
        manager.out(f"  error: {error['path']}: {error['error']}")
    manager.out(f"uninstall {'complete' if result['ok'] else 'finished with errors'}")
    return 0 if result["ok"] else 1


def _cmd_plugin(args) -> int:
    from .plugin import PluginManager
    manager = PluginManager()
    if args.plugin_command == "status":
        return _cmd_plugin_status(manager, args.json)
    if args.plugin_command == "install":
        if _plugin_scope(args) == "project":
            result = manager.install_project(
                args.project_path, local_hosts=args.local_hosts,
                hooks=args.hooks, dry_run=args.dry_run,
            )
            return _cmd_plugin_run(f"install --project {args.project_path}", result, manager)
        result = manager.install_global(args.hosts, dry_run=args.dry_run)
        return _cmd_plugin_run("install --global", result, manager)
    if args.plugin_command == "update":
        if _plugin_scope(args) == "project":
            result = manager.update_project(args.project_path, dry_run=args.dry_run)
            return _cmd_plugin_run(f"update --project {args.project_path}", result, manager)
        result = manager.update_global(dry_run=args.dry_run)
        return _cmd_plugin_run("update --global", result, manager)
    if args.plugin_command == "uninstall":
        return _cmd_plugin_uninstall(args, manager)
    return 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="gsd-path-daemon",
        description="Progress-monitoring daemon for GSD Path projects",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", default=None, help="path to daemon.json (overrides GSD_DAEMON_CONFIG)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan", help="list detected projects as JSON")
    commands.add_parser("dump", help="full aggregated status JSON")
    serve_parser = commands.add_parser("serve", help="localhost status HTTP server")
    serve_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    tray_parser = commands.add_parser("tray", help="run the system tray app (requires the tray extra)")
    tray_parser.add_argument("--serve", action="store_true",
                             help="also run the dashboard HTTP server in a background thread")
    tray_parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                             help="dashboard port used with --serve")
    install_parser = commands.add_parser("install", help="install into a venv and register autostart")
    install_parser.add_argument("--no-tray", action="store_true",
                                help="skip the tray extra and the native tray app")
    install_parser.add_argument("--no-autostart", action="store_true",
                                help="install only; do not register autostart")
    install_parser.add_argument("--dry-run", action="store_true",
                                help="print every action without executing it")
    uninstall_parser = commands.add_parser("uninstall", help="remove autostart registration")
    uninstall_parser.add_argument("--dry-run", action="store_true",
                                  help="print every action without executing it")
    plugin_parser = commands.add_parser(
        "plugin", help="manage the gsd-path skill plugin (install/update/uninstall)")
    plugin_commands = plugin_parser.add_subparsers(dest="plugin_command", required=True)
    plugin_status = plugin_commands.add_parser("status", help="detected installs and update state")
    plugin_status.add_argument("--json", action="store_true")
    plugin_install = plugin_commands.add_parser("install", help="install the plugin")
    install_scope = plugin_install.add_mutually_exclusive_group(required=True)
    install_scope.add_argument("--global", dest="global_scope", action="store_true",
                               help="install into per-host global skill roots")
    install_scope.add_argument("--project", dest="project_path", default=None,
                               help="install project contracts into PATH")
    plugin_install.add_argument("--host", dest="hosts", action="append", default=None,
                                help="limit global install to this host (repeatable)")
    plugin_install.add_argument("--local", dest="local_hosts", action="append", default=None,
                                metavar="HOST",
                                help="also install project-local skills for HOST (repeatable)")
    plugin_install.add_argument("--hooks", action="store_true",
                                help="install guard hooks with --project")
    plugin_install.add_argument("--dry-run", action="store_true")
    plugin_update = plugin_commands.add_parser("update", help="update existing installs")
    update_scope = plugin_update.add_mutually_exclusive_group()
    update_scope.add_argument("--global", dest="global_scope", action="store_true",
                              help="update global installs (default)")
    update_scope.add_argument("--project", dest="project_path", default=None,
                              help="update the project install at PATH")
    plugin_update.add_argument("--dry-run", action="store_true")
    plugin_uninstall = plugin_commands.add_parser("uninstall", help="remove the plugin")
    uninstall_scope = plugin_uninstall.add_mutually_exclusive_group(required=True)
    uninstall_scope.add_argument("--global", dest="global_scope", action="store_true",
                                 help="uninstall from per-host global skill roots")
    uninstall_scope.add_argument("--project", dest="project_path", default=None,
                                 help="uninstall from the project at PATH")
    plugin_uninstall.add_argument("--host", dest="hosts", action="append", default=None,
                                  help="limit global uninstall to this host (repeatable)")
    plugin_uninstall.add_argument("--dry-run", action="store_true",
                                  help="print the removal plan without applying it")
    plugin_uninstall.add_argument("--yes", action="store_true",
                                  help="apply the removal plan (required without --dry-run)")
    args = parser.parse_args(argv)

    config = Config.load(args.config)

    if args.command == "scan":
        print(json.dumps(_cmd_scan(config), indent=2, sort_keys=True))
        return 0
    if args.command == "dump":
        print(json.dumps(_cmd_dump(config), indent=2, sort_keys=True))
        return 0
    if args.command == "serve":
        from . import serve as serve_module
        serve_module.run(Watcher(config), port=args.port)
        return 0
    if args.command == "tray":
        try:
            from . import tray
        except ImportError as error:
            print(f"tray requires optional dependencies: pip install 'gsd-path-daemon[tray]' ({error})",
                  file=sys.stderr)
            return 1
        tray.run(config, config_path=args.config,
                 serve_port=args.port if args.serve else None)
        return 0
    if args.command == "install":
        from .installer import Installer
        installer = Installer(dry_run=args.dry_run)
        return installer.install(no_tray=args.no_tray, no_autostart=args.no_autostart)
    if args.command == "uninstall":
        from .installer import Installer
        installer = Installer(dry_run=args.dry_run)
        return installer.uninstall()
    if args.command == "plugin":
        return _cmd_plugin(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
