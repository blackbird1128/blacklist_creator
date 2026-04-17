#!/usr/bin/env python3

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run blacklister.py over selected files from a _CoqProject."
    )
    parser.add_argument(
        "coqproject",
        type=Path,
        help="Path to the _CoqProject file that defines file order and rocq flags.",
    )
    parser.add_argument(
        "blacklist",
        type=Path,
        help="Path to a file listing .v files to consider for blacklisting.",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Directory where the rewritten/copied tree will be created.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Forwarded to blacklister.py when it is invoked.",
    )
    return parser.parse_args()


def load_coqproject(coqproject: Path) -> tuple[list[str], list[Path]]:
    rocq_flags: list[str] = []
    base_dir = coqproject.parent

    for raw_line in coqproject.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = shlex.split(line)
        if not parts:
            continue

        if parts[0].startswith("-"):
            i = 0
            while i < len(parts):
                if parts[i] == "-arg":
                    if i + 1 >= len(parts):
                        raise RuntimeError(f"Dangling -arg in {coqproject}: {raw_line}")
                    rocq_flags.append(parts[i + 1])
                    i += 2
                    continue
                rocq_flags.append(parts[i])
                i += 1
    dep_result = subprocess.run(
        ["rocq", "dep", "-f", str(coqproject), "-sort"],
        cwd=base_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if dep_result.returncode != 0:
        raise RuntimeError(
            f"rocq dep failed for {coqproject}:\n{dep_result.stderr.strip()}"
        )

    files = [
        Path(path).resolve().relative_to(base_dir.resolve())
        for path in shlex.split(dep_result.stdout)
    ]

    return rocq_flags, files


def load_blacklist(blacklist_path: Path) -> set[Path]:
    entries: set[Path] = set()

    for raw_line in blacklist_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(Path(line))

    return entries


def is_blacklisted(relative_file: Path, blacklist: set[Path]) -> bool:
    relative_parts = relative_file.parts
    for entry in blacklist:
        entry_parts = entry.parts
        if (
            len(entry_parts) <= len(relative_parts)
            and relative_parts[-len(entry_parts):] == entry_parts
        ):
            return True
    return False


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def rocq_typechecks(file_path: Path, rocq_flags: list[str], cwd: Path) -> bool:
    result = subprocess.run(
        ["rocq", "c", *rocq_flags, str(file_path)],
        cwd=cwd,
        stdout=subprocess.STDOUT,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return result.returncode == 0


def rocq_compile(file_path: Path, rocq_flags: list[str], cwd: Path) -> None:
    result = subprocess.run(
        ["rocq", "c", *rocq_flags, str(file_path)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"rocq c failed for {file_path}:\n{result.stderr.strip()}"
        )


def run_blacklister(
    source_file: Path,
    target_file: Path,
    workers: int | None,
    script_dir: Path,
) -> None:
    ensure_parent(target_file)

    command = [sys.executable, str(script_dir / "blacklister.py")]
    if workers is not None:
        command.extend(["--workers", str(workers)])
    command.append(str(source_file))

    result = subprocess.run(
        command,
        cwd=script_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"blacklister.py failed for {source_file}:\n{result.stderr.strip()}"
        )

    target_file.write_text(result.stdout)


def main() -> int:

    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    coqproject : Path = args.coqproject.resolve()
    blacklist_path : Path = args.blacklist.resolve()
    output_dir: Path =  args.output_dir.resolve()
    project_root = coqproject.parent

    rocq_flags, ordered_files = load_coqproject(coqproject)
    blacklist = load_blacklist(blacklist_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(coqproject, output_dir / coqproject.name)

    for relative_file in ordered_files:
        source_file = (project_root / relative_file).resolve()
        target_file = output_dir / relative_file
        print(f"running on {source_file}")

        if not source_file.exists():
            raise FileNotFoundError(f"Missing source file listed in _CoqProject: {relative_file}")

        ensure_parent(target_file)

        if not is_blacklisted(relative_file, blacklist):
            shutil.copy2(source_file, target_file)
        elif rocq_typechecks(source_file, rocq_flags, project_root):
            shutil.copy2(source_file, target_file)
        else:
            run_blacklister(source_file, target_file, args.workers, script_dir)

        
        rocq_compile(target_file.relative_to(output_dir), rocq_flags, output_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
