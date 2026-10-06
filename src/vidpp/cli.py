from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import shlex
import subprocess
import sys
import shutil
import tempfile

from .core import analyze, create_project, plan, project_hook, refresh_source_metadata, save_project_hook, save_transcript, transcribe
from .config import AppConfig, app_config, apply_project_config, read_project_config
from .errors import VidPPError
from .render import render
from .template import load_template

LOG = logging.getLogger(__name__)


class VidPPArgumentParser(argparse.ArgumentParser):
    """Keep the overview concise and accept the literal 'help' command argument."""

    def parse_args(self, args=None, namespace=None):
        values = list(sys.argv[1:] if args is None else args)
        if not values:
            self.print_help()
            self.exit()
        return super().parse_args(values, namespace)

    def parse_known_args(self, args=None, namespace=None):
        values = list(sys.argv[1:] if args is None else args)
        if values == ["help"]:
            values = ["--help"]
        return super().parse_known_args(values, namespace)


def _project(value: str) -> Path: return Path(value).expanduser()


def _project_name(value: str) -> Path:
    if not value or value in {".", "..", ".vidpp"} or Path(value).name != value or "/" in value or "\\" in value:
        raise argparse.ArgumentTypeError("project name must be one directory name without path separators")
    return Path(value if value.endswith(".vidpp") else value + ".vidpp")


def _resolve_project(value: Path, projects_dir: Path, *, existing: bool) -> Path:
    project = value.expanduser()
    if not project.is_absolute():
        project = projects_dir / project
    project = project.resolve()
    if existing and not project.exists() and project.suffix != ".vidpp":
        suffixed = project.with_name(project.name + ".vidpp")
        if suffixed.exists():
            project = suffixed
    return project


def _output_file(project: Path, explicit: Path | None, config: AppConfig) -> Path | None:
    if explicit is not None:
        return explicit.expanduser().resolve()
    if config.output_file_dir is not None:
        return config.output_file_dir / f"{project.stem}.mp4"
    return None


def _list_projects(projects_dir: Path) -> list[Path]:
    if not projects_dir.exists():
        return []
    if not projects_dir.is_dir():
        raise VidPPError(f"projects_dir is not a directory: {projects_dir}")
    projects = []
    for item in projects_dir.iterdir():
        if item.is_dir() and ((item / "project.json").is_file() or (item / "config.yaml").is_file()):
            values = read_project_config(item)
            if isinstance(values.get("source_path"), str):
                projects.append(item)
    return sorted(projects, key=lambda item: item.name.casefold())


def _prepare_project_destination(project: Path, sources: list[Path], replace: bool) -> None:
    if not replace or (not project.exists() and not project.is_symlink()):
        return
    if project.is_symlink():
        raise VidPPError(f"refusing to replace a symlinked project destination: {project}")
    if not project.is_dir():
        raise VidPPError(f"project destination is not a directory: {project}")
    target = project.resolve()
    protected = {Path("/").resolve(), Path.cwd().resolve(), Path.home().resolve(), Path(tempfile.gettempdir()).resolve()}
    if target in protected or target in Path.cwd().resolve().parents:
        raise VidPPError(f"refusing to replace protected directory: {target}")
    for source in sources:
        absolute_source = source.absolute()
        resolved_source = source.resolve()
        if (absolute_source == target or target in absolute_source.parents or
                resolved_source == target or target in resolved_source.parents):
            raise VidPPError(f"refusing to replace project because it contains source media: {source}")
    if target.suffix != ".vidpp":
        has_config = (target / "project.json").is_file() or (target / "config.yaml").is_file()
        if not has_config or not isinstance(read_project_config(target).get("source_path"), str):
            raise VidPPError(f"refusing to replace directory that is not recognizably a VidPP project: {target}")
    LOG.warning("Replacing project: removing existing destination %s", target)
    shutil.rmtree(target)


def _hook_override(project: Path, command_hook: str | None) -> str | None:
    if command_hook is not None:
        save_project_hook(project, command_hook)
        return command_hook
    return project_hook(project)


def _save_effective_hook(project: Path, hook: str, override: str | None) -> None:
    # A template hook becomes project-specific only when no hook has already been saved.
    if override is not None or hook:
        save_project_hook(project, hook)


def open_video(path: Path) -> None:
    """Open a completed video with the platform's default viewer without waiting."""
    target = path.resolve()
    if not target.is_file():
        raise VidPPError(f"rendered video does not exist: {target}")
    LOG.info("Opening rendered video in the default viewer: %s", target)
    try:
        if sys.platform == "win32":
            startfile = getattr(os, "startfile", None)
            if startfile is None:
                raise OSError("os.startfile is unavailable")
            LOG.debug("Opening video with os.startfile: %s", target)
            startfile(str(target))
            return
        command = ["open" if sys.platform == "darwin" else "xdg-open", str(target)]
        LOG.debug("Executing desktop opener: %s", shlex.join(command))
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise VidPPError(f"could not open rendered video with the default viewer: {exc}") from exc


def parser() -> argparse.ArgumentParser:
    app = VidPPArgumentParser(
        prog="vidpp", usage="%(prog)s [-h] [-v] <command> ...",
        description="Process videos locally.", formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Example: create a project from a video and hook:\n  vidpp process input.mp4 --hook "Why privacy matters"\n\nCommand details: vidpp <command> help (or -h, --help)',
    )
    app.add_argument("-v", "--verbose", action="count", default=0, help="enable debug logging before the command")
    commands = app.add_subparsers(dest="command", required=True, title="commands", metavar="<command>")

    def command(name: str, summary: str, description: str):
        return commands.add_parser(name, help=summary, description=description,
                                   epilog=f"Global options: -v, --verbose enable debug logging before the command: vidpp -v {name} ...")

    command("list", "list saved projects", "List projects in the configured projects directory, migrating legacy configurations when needed.")
    import_cmd = command("import", "create a project from input videos", "Create a project referencing one or more input videos. Multiple inputs are combined in the supplied order.")
    import_cmd.add_argument("sources", type=Path, nargs="+", help="input video paths, in timeline order")
    import_cmd.add_argument("project", type=Path, help="project destination; relative paths use the configured projects directory")
    import_cmd.add_argument("--project-config", type=Path, help="YAML overrides to merge into the new project's config.yaml")
    import_cmd.add_argument("--replace-project", action="store_true", help="remove and recreate the destination project")
    stage_help = {
        "transcribe": ("generate or import a transcript", "Transcribe speech using the configured model, or import an existing timestamped transcript."),
        "analyze": ("analyze audio and pauses", "Analyze the project's audio for long pauses and save analysis.json."),
        "plan": ("propose edits for review", "Generate a semantic edit plan and save proposals in edit.json for review before enabling them."),
        "render": ("render the final video", "Render the final MP4 using the saved transcript, enabled edits, project settings, and optional visual template."),
        "preview": ("render a fast video preview", "Render a lower-quality preview to the project's previews directory using the current settings and enabled edits."),
    }
    for name, descriptions in stage_help.items():
        cmd = command(name, *descriptions)
        cmd.add_argument("project", type=_project, help="project name or absolute project directory")
        cmd.add_argument("--template", type=Path, help="visual/editing template YAML" if name != "transcribe" else "accepted for compatibility; unused during transcription")
        cmd.add_argument("--hook", help="save the project hook; an empty string clears it")
        if name == "transcribe": cmd.add_argument("--transcript", type=Path, help="import a timestamped JSON transcript instead of running a model")
        if name in {"render", "preview"}:
            cmd.add_argument("--format", dest="output_format", metavar="p720", help="output short-edge resolution, such as p360, p720 or p1080")
            cmd.add_argument("--orientation", choices=("auto", "portrait", "landscape"), help="output orientation; auto follows the source")
            cmd.add_argument("--no-edit", action="store_true", help="ignore edit.json and keep the complete timeline")
        if name == "render":
            cmd.add_argument("--open", action="store_true", help="open the completed video in the default viewer")
            cmd.add_argument("--output-file", type=Path, help="write the final MP4 to this path")
    process = command("process", "create a project and process its videos", "Create a project, transcribe speech, analyze audio, propose edits, and render the result. Review proposed edits before enabling them.")
    process.add_argument("sources", type=Path, nargs="+", help="input video paths, in timeline order")
    destination = process.add_mutually_exclusive_group()
    destination.add_argument("--project", type=Path, help="project destination path")
    destination.add_argument("--project-name", type=_project_name, help="project directory name; .vidpp is appended")
    process.add_argument("--replace-project", action="store_true", help="remove and recreate the destination project")
    process.add_argument("--no-edit", action="store_true", help="skip edit analysis/planning and keep the complete timeline")
    process.add_argument("--open", action="store_true", help="open the completed video in the default viewer")
    process.add_argument("--output-file", type=Path, help="write the final MP4 to this path")
    process.add_argument("--template", type=Path, help="visual/editing template YAML")
    process.add_argument("--hook", help="project hook text; an empty string disables the hook")
    process.add_argument("--transcript", type=Path, help="import a timestamped JSON transcript instead of running a model")
    process.add_argument("--project-config", type=Path, help="YAML overrides to merge into the new project's config.yaml")
    process.add_argument("--format", dest="output_format", metavar="p720", help="output short-edge resolution, such as p360, p720 or p1080")
    process.add_argument("--orientation", choices=("auto", "portrait", "landscape"), help="output orientation; auto follows the source")
    return app


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = app_config()
        LOG.debug("Application paths: projects_dir=%s, output_file_dir=%s", config.projects_dir, config.output_file_dir)
        if args.command == "list":
            for project in _list_projects(config.projects_dir):
                print(project.name)
            return 0
        if args.command in {"import", "process"} and args.project_config and not args.project_config.is_file():
            raise VidPPError(f"project configuration does not exist: {args.project_config}")
        if args.command == "import":
            args.project = _resolve_project(args.project, config.projects_dir, existing=False)
            LOG.info("Inspecting source and creating project...")
            _prepare_project_destination(args.project, args.sources, args.replace_project)
            create_project(args.sources, args.project)
            if args.project_config: apply_project_config(args.project, args.project_config)
            print(f"Created project: {args.project}")
            return 0
        if args.command == "process":
            project_value = args.project or args.project_name or Path(args.sources[0].stem + ".vidpp")
            project = _resolve_project(project_value, config.projects_dir, existing=False)
            LOG.info("Inspecting source and creating project...")
            _prepare_project_destination(project, args.sources, args.replace_project)
            metadata = create_project(args.sources, project)
            if args.project_config: apply_project_config(project, args.project_config)
            source = metadata["source"]
            template = load_template(args.template, _hook_override(project, args.hook), source_width=source["width"], source_height=source["height"], output_format=args.output_format, orientation=args.orientation)
            _save_effective_hook(project, template.hook_text, args.hook)
            LOG.info("Output format: %dx%d", template.width, template.height)
            if args.transcript:
                LOG.info("Importing supplied transcript...")
                save_transcript(project, args.transcript)
            else:
                transcribe(project)
            operations = []
            if args.no_edit:
                LOG.info("Editing disabled; skipping audio edit analysis and editorial planning.")
            else:
                LOG.info("Analyzing audio...")
                analyze(project, template)
                LOG.info("Planning edits...")
                operations = plan(project, template)
            LOG.info("Rendering final video...")
            target = render(
                project,
                template,
                apply_edits=not args.no_edit,
                output_file=_output_file(project, args.output_file, config),
            )
            if args.open:
                open_video(target)
            if args.no_edit:
                print(f"Editing disabled. Done: {target}")
                return 0
            enabled = sum(item.enabled and item.type != "review" for item in operations)
            print(f"{len(operations)} proposed edits, {enabled} enabled. Done: {target}"); return 0
        args.project = _resolve_project(args.project, config.projects_dir, existing=True)
        if args.command == "transcribe":
            if args.hook is not None:
                save_project_hook(args.project, args.hook)
            if args.transcript:
                LOG.info("Importing supplied transcript...")
                save_transcript(args.project, args.transcript)
            else:
                transcribe(args.project)
        elif args.command == "analyze":
            LOG.info("Analyzing audio...")
            metadata = refresh_source_metadata(args.project)
            hook = _hook_override(args.project, args.hook)
            template = load_template(args.template, hook, source_width=metadata["width"], source_height=metadata["height"])
            _save_effective_hook(args.project, template.hook_text, hook)
            analyze(args.project, template)
        elif args.command == "plan":
            LOG.info("Planning edits...")
            metadata = refresh_source_metadata(args.project)
            hook = _hook_override(args.project, args.hook)
            template = load_template(args.template, hook, source_width=metadata["width"], source_height=metadata["height"])
            _save_effective_hook(args.project, template.hook_text, hook)
            operations = plan(args.project, template)
            enabled = sum(item.enabled and item.type != "review" for item in operations)
            print(f"{len(operations)} proposed edits, {enabled} enabled; review {args.project / 'edit.json'}.")
        else:
            LOG.info("Rendering %s...", "preview" if args.command == "preview" else "final video")
            metadata = refresh_source_metadata(args.project)
            hook = _hook_override(args.project, args.hook)
            template = load_template(args.template, hook, source_width=metadata["width"], source_height=metadata["height"], output_format=args.output_format, orientation=args.orientation)
            _save_effective_hook(args.project, template.hook_text, hook)
            LOG.info("Output format: %dx%d", template.width, template.height)
            target = render(
                args.project,
                template,
                preview=args.command == "preview",
                apply_edits=not args.no_edit,
                output_file=_output_file(args.project, args.output_file, config) if args.command == "render" else None,
            )
            if args.command == "render" and args.open:
                open_video(target)
            print(f"Done: {target}")
        return 0
    except VidPPError as exc:
        logging.error("%s", exc); return 2


if __name__ == "__main__": raise SystemExit(main())
