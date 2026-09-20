from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
import shutil
import tempfile

from .core import analyze, create_project, plan, project_hook, refresh_source_metadata, save_project_hook, save_transcript, transcribe
from .errors import VidPPError
from .render import render
from .template import load_template

LOG = logging.getLogger(__name__)


class VidPPArgumentParser(argparse.ArgumentParser):
    """Show command-specific options in the root help, not only command names."""

    def format_help(self) -> str:
        help_text = super().format_help()
        subparsers = next(
            (action for action in self._actions if isinstance(action, argparse._SubParsersAction)),
            None,
        )
        if subparsers is None:
            return help_text
        sections = [help_text.rstrip(), "", "command options:"]
        for name, command_parser in subparsers.choices.items():
            sections.extend(["", f"  {name}", command_parser.format_help().rstrip()])
        return "\n".join(sections) + "\n"


def _project(value: str) -> Path: return Path(value).resolve()


def _project_name(value: str) -> Path:
    if not value or value in {".", "..", ".vidpp"} or Path(value).name != value or "/" in value or "\\" in value:
        raise argparse.ArgumentTypeError("project name must be one directory name without path separators")
    return Path(value if value.endswith(".vidpp") else value + ".vidpp")


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
    if target.suffix != ".vidpp" and not (target / "project.json").is_file():
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


def parser() -> argparse.ArgumentParser:
    app = VidPPArgumentParser(prog="vidpp", description="Local, deterministic social-video post-processing")
    app.add_argument("-v", "--verbose", action="count", default=0)
    commands = app.add_subparsers(dest="command", required=True)
    import_cmd = commands.add_parser("import", help="create a project without copying source media")
    import_cmd.add_argument("sources", type=Path, nargs="+"); import_cmd.add_argument("project", type=Path)
    import_cmd.add_argument("--project-config", type=Path)
    import_cmd.add_argument("--replace-project", action="store_true", help="remove and recreate the destination project")
    for name in ("transcribe", "analyze", "plan", "render", "preview"):
        cmd = commands.add_parser(name); cmd.add_argument("project", type=_project); cmd.add_argument("--template", type=Path); cmd.add_argument("--hook")
        if name == "transcribe": cmd.add_argument("--transcript", type=Path)
        if name in {"render", "preview"}:
            cmd.add_argument("--format", dest="output_format", metavar="p720")
            cmd.add_argument("--orientation", choices=("auto", "portrait", "landscape"))
            cmd.add_argument("--no-edit", action="store_true", help="ignore edit.json and keep the complete timeline")
    process = commands.add_parser("process", help="run the complete pipeline")
    process.add_argument("sources", type=Path, nargs="+")
    destination = process.add_mutually_exclusive_group()
    destination.add_argument("--project", type=Path, help="project destination path")
    destination.add_argument("--project-name", type=_project_name, help="project directory name; .vidpp is appended")
    process.add_argument("--replace-project", action="store_true", help="remove and recreate the destination project")
    process.add_argument("--no-edit", action="store_true", help="skip edit analysis/planning and keep the complete timeline")
    process.add_argument("--template", type=Path); process.add_argument("--hook"); process.add_argument("--transcript", type=Path)
    process.add_argument("--project-config", type=Path)
    process.add_argument("--format", dest="output_format", metavar="p720")
    process.add_argument("--orientation", choices=("auto", "portrait", "landscape"))
    return app


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.command in {"import", "process"} and args.project_config and not args.project_config.is_file():
            raise VidPPError(f"project configuration does not exist: {args.project_config}")
        if args.command == "import":
            LOG.info("Inspecting source and creating project...")
            _prepare_project_destination(args.project, args.sources, args.replace_project)
            create_project(args.sources, args.project)
            if args.project_config: shutil.copyfile(args.project_config, args.project / "config.yaml")
            print(f"Created project: {args.project}")
            return 0
        if args.command == "process":
            project = args.project or args.project_name or Path(args.sources[0].stem + ".vidpp")
            LOG.info("Inspecting source and creating project...")
            _prepare_project_destination(project, args.sources, args.replace_project)
            metadata = create_project(args.sources, project)
            source = metadata["source"]
            template = load_template(args.template, args.hook, source_width=source["width"], source_height=source["height"], output_format=args.output_format, orientation=args.orientation)
            _save_effective_hook(project, template.hook_text, args.hook)
            LOG.info("Output format: %dx%d", template.width, template.height)
            if args.project_config: shutil.copyfile(args.project_config, project / "config.yaml")
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
            target = render(project, template, apply_edits=not args.no_edit)
            if args.no_edit:
                print(f"Editing disabled. Done: {target}")
                return 0
            enabled = sum(item.enabled and item.type != "review" for item in operations)
            print(f"{len(operations)} proposed edits, {enabled} enabled. Done: {target}"); return 0
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
            print(f"Done: {render(args.project, template, preview=args.command == 'preview', apply_edits=not args.no_edit)}")
        return 0
    except VidPPError as exc:
        logging.error("%s", exc); return 2


if __name__ == "__main__": raise SystemExit(main())
