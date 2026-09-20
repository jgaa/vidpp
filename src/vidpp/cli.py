from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
import shutil

from .core import analyze, create_project, plan, save_transcript, transcribe
from .errors import VidPPError
from .render import render
from .template import load_template

LOG = logging.getLogger(__name__)


def _project(value: str) -> Path: return Path(value).resolve()


def parser() -> argparse.ArgumentParser:
    app = argparse.ArgumentParser(prog="vidpp", description="Local, deterministic social-video post-processing")
    app.add_argument("-v", "--verbose", action="count", default=0)
    commands = app.add_subparsers(dest="command", required=True)
    import_cmd = commands.add_parser("import", help="create a project without copying source media")
    import_cmd.add_argument("source", type=Path); import_cmd.add_argument("project", type=Path)
    import_cmd.add_argument("--project-config", type=Path)
    for name in ("transcribe", "analyze", "plan", "render", "preview"):
        cmd = commands.add_parser(name); cmd.add_argument("project", type=_project); cmd.add_argument("--template", type=Path); cmd.add_argument("--hook")
        if name == "transcribe": cmd.add_argument("--transcript", type=Path)
    process = commands.add_parser("process", help="run the complete pipeline")
    process.add_argument("source", type=Path); process.add_argument("--project", type=Path); process.add_argument("--template", type=Path); process.add_argument("--hook"); process.add_argument("--transcript", type=Path)
    process.add_argument("--project-config", type=Path)
    return app


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.command in {"import", "process"} and args.project_config and not args.project_config.is_file():
            raise VidPPError(f"project configuration does not exist: {args.project_config}")
        if args.command == "import":
            LOG.info("Inspecting source and creating project...")
            create_project(args.source, args.project)
            if args.project_config: shutil.copyfile(args.project_config, args.project / "config.yaml")
            print(f"Created project: {args.project}")
            return 0
        if args.command == "process":
            project = args.project or Path(args.source.stem + ".vidpp")
            LOG.info("Inspecting source and creating project...")
            create_project(args.source, project); template = load_template(args.template, args.hook)
            if args.project_config: shutil.copyfile(args.project_config, project / "config.yaml")
            if args.transcript:
                LOG.info("Importing supplied transcript...")
                save_transcript(project, args.transcript)
            else:
                transcribe(project)
            LOG.info("Analyzing audio...")
            analyze(project, template)
            LOG.info("Planning edits...")
            operations = plan(project, template)
            LOG.info("Rendering final video...")
            target = render(project, template)
            print(f"{len(operations)} proposed edits. Done: {target}"); return 0
        template = load_template(args.template, args.hook)
        if args.command == "transcribe":
            if args.transcript:
                LOG.info("Importing supplied transcript...")
                save_transcript(args.project, args.transcript)
            else:
                transcribe(args.project)
        elif args.command == "analyze":
            LOG.info("Analyzing audio...")
            analyze(args.project, template)
        elif args.command == "plan":
            LOG.info("Planning edits...")
            print(f"{len(plan(args.project, template))} proposed edits.")
        else:
            LOG.info("Rendering %s...", "preview" if args.command == "preview" else "final video")
            print(f"Done: {render(args.project, template, preview=args.command == 'preview')}")
        return 0
    except VidPPError as exc:
        logging.error("%s", exc); return 2


if __name__ == "__main__": raise SystemExit(main())
