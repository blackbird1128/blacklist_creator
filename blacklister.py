import argparse
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

type Proof = tuple[str, str, str, re.Match[str]]
type RocqResult = subprocess.CompletedProcess[bytes]

parser = argparse.ArgumentParser(prog="blacklist maker",description="")
parser.add_argument('filename',type=str)  # pyright: ignore[reportUnusedCallResult]
parser.add_argument('--theories-dir', type=Path, default=None, help="Root theories directory to pass to rocq -Q")  # pyright: ignore[reportUnusedCallResult]
parser.add_argument('--workers', type=int, default=None, help="Number of proofs to check in parallel (defaults to CPU count)")  # pyright: ignore[reportUnusedCallResult]
proof_pattern = r"(^[ \t]*(?:Goal|Lemma|Global Instance|Instance|Definition)\b.*?)Proof(?:\s+using\s+[^.]*)?\.(.*?)(Qed|Admitted|Abort|Defined)\."
proof_pattern_c : re.Pattern[str] = re.compile(proof_pattern, re.DOTALL | re.MULTILINE)
name_pattern =  r"(?:Lemma|Instance|Global Instance|Definition)\s(.*?)\:"
name_pattern_c : re.Pattern[str] = re.compile(name_pattern,re.DOTALL)
file_line_pattern : re.Pattern[str] = re.compile(r'.*File ".*", line \d+, characters \d+-\d+:$')
UNSTABLE_GOAL_ERROR = "Could not deduce the stability of the goal"
UNSTABLE_GOAL_COMMENT = "Can't be imported by wholesale importation (Case analysis on an unstable goal)"
TERMINATOR_COMMENT_PREFIX = "blacklister-original-terminator:"
DECLARATION_PREFIX = r"(?:Goal|Lemma|Global Instance|Instance|Definition)"
blacklisted_proof_pattern: re.Pattern[str] = re.compile(
    rf"(?P<header>^[ \t]*{DECLARATION_PREFIX}\b"
    rf"(?:(?!^[ \t]*{DECLARATION_PREFIX}\b).)*?)"
    rf"Proof(?:\s+using\s+[^.]*)?\.\s*\n"
    rf"(?P<comment_prefix>(?:[ \t]*\(\*(?! {re.escape(TERMINATOR_COMMENT_PREFIX)}).*?\*\)[ \t]*\n)*)"
    rf"\(\* {re.escape(TERMINATOR_COMMENT_PREFIX)} "
    rf"(?P<terminator>Qed|Admitted|Abort|Defined) \*\)\s*\n"
    rf"\(\* (?P<proof>.*?) \*\)Admitted\.",
    re.DOTALL | re.MULTILINE,
)
terminator_comment_pattern: re.Pattern[str] = re.compile(
    rf"^[ \t]*\(\* {re.escape(TERMINATOR_COMMENT_PREFIX)} "
    rf"(?:Qed|Admitted|Abort|Defined) \*\)[ \t]*\n",
    re.MULTILINE,
)

def extract_proofs (text: str) -> list[Proof]:
    matches: list[re.Match[str]] =  list(proof_pattern_c.finditer(text))
    return [(m.groups()[0].lstrip(), m.groups()[1], m.groups()[2], m) for m in matches if not (m.groups()[1].strip().startswith("(*"))]

def extract_proof_name (proof_prop: str) -> str:
  matches: list[str] = name_pattern_c.findall(proof_prop)
  if matches == []:
      return "anonymous"
  else:
      return matches[0].strip()

def proof_stub(
    match: re.Match[str],
    comment: str | None = None,
) -> str:
    comments = []
    if comment:
        comments.append(f"(* {comment} *)")
    comments.append(f"(* {TERMINATOR_COMMENT_PREFIX} {match.group(3)} *)")
    comments.append(f"(* {match.group(2)} *)Admitted.")
    return f"{match.group(1)}Proof.\n" + "\n".join(comments)

def comment_proofs (text: str) -> str:
    return proof_pattern_c.sub(lambda match: proof_stub(match), text)

def comment_proofs_until (text: str, n: int) -> str:
    if n <= 0:
        return text

    return proof_pattern_c.sub(lambda match: proof_stub(match), text, count=n)

def comment_only_unsafe(
    text: str,
    unsafe_matches: list[re.Match[str]],
    unsafe_comments: dict[tuple[int, int], str] | None = None,
) -> str:
    unsafe_set = set(m.span() for m in unsafe_matches)
    def repl(match: re.Match[str]) -> str:
        span = match.span()
        if span in unsafe_set:
            comment = unsafe_comments.get(span, "blacklisted") if unsafe_comments else "blacklisted"
            return proof_stub(match, comment)
        else:
            return match.group(0)  # leave unchanged

    return proof_pattern_c.sub(repl, text)
    
def file_upto (m: re.Match[str],text: str):
   return text[0:m.end()]

def file_after (m: re.Match[str], text: str):
    return text[m.end():]

def remove_warning_blocks(output: str) -> str:
    lines = output.splitlines()
    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in lines:
        stripped = line.strip()
        if file_line_pattern.match(stripped):
            if current_block:
                blocks.append(current_block)
            current_block = [line]
        else:
            if not current_block:
                current_block = [line]
            else:
                current_block.append(line)

    if current_block:
        blocks.append(current_block)

    filtered_lines: list[str] = []
    for block in blocks:
        has_error = any("Error:" in entry for entry in block)
        has_warning = any("Warning:" in entry for entry in block)

        if has_warning and not has_error:
            continue

        filtered_lines.extend(block)

    return "\n".join(filtered_lines)


def update_progress(current: int, total: int) -> None:
    bar_length = 40
    ratio = current / total if total else 0
    filled_length = int(bar_length * ratio)
    bar = "#" * filled_length + "-" * (bar_length - filled_length)
    sys.stderr.write(f"\r[{bar}] {current}/{total}")
    sys.stderr.flush()


def run_rocq_on_text(
    text: str,
    filename_without_ext: str,
    theories_dir: Path,
    capture_output: bool,
) -> RocqResult:
    with tempfile.NamedTemporaryFile(
        mode="w",
        delete_on_close=True,
        suffix=".v",
        prefix=filename_without_ext,
    ) as fp:
        _ = fp.write(text)
        fp.flush()

        return subprocess.run(
            [
                "rocq",
                "c",
                "-Q",
                str(theories_dir),
                "GeoCoq",
                "-w",
                "-ambiguous-paths",
                "-w",
                "notation-overridden",
                fp.name,
            ],
            capture_output=capture_output,
            stdout=None if capture_output else subprocess.DEVNULL,
            stderr=None if capture_output else subprocess.DEVNULL,
            check=False,
        )

def compile_text(text: str, filename_without_ext: str, theories_dir: Path) -> bool:
    result = run_rocq_on_text(
        text,
        filename_without_ext,
        theories_dir,
        capture_output=False,
    )
    return result.returncode == 0


def restore_blacklisted_proof(match: re.Match[str]) -> str:
    return (
        f"{match.group('header')}"
        f"Proof.{match.group('proof')}"
        f"{match.group('terminator')}."
    )


def replace_span(text: str, span: tuple[int, int], replacement: str) -> str:
    start, end = span
    return text[:start] + replacement + text[end:]


def cleanup_pass(
    text: str,
    filename_without_ext: str,
    theories_dir: Path,
) -> tuple[str, list[str]]:
    restored_names: list[str] = []
    search_start = 0

    while True:
        match = blacklisted_proof_pattern.search(text, search_start)
        if not match:
            break

        name = extract_proof_name(match.group("header"))
        restored = restore_blacklisted_proof(match)
        candidate = replace_span(text, match.span(), restored)

        if compile_text(candidate, filename_without_ext, theories_dir):
            text = candidate
            restored_names.append(name)
            search_start = match.start() + len(restored)
            print(f"restored {name}", file=sys.stderr)
        else:
            search_start = match.end()
            print(f"kept blacklisted {name}", file=sys.stderr)

    return text, restored_names


def cleanup_blacklisted_proofs(
    text: str,
    filename_without_ext: str,
    theories_dir: Path,
) -> tuple[str, set[str]]:
    pass_number = 0
    restored_names: set[str] = set()
    # For now, only one pass is needed, speed up a bit
    # while True:
    #     pass_number += 1
    #     print(f"cleanup pass {pass_number}", file=sys.stderr)
    text, pass_restored_names = cleanup_pass(text, filename_without_ext, theories_dir)
    restored_names.update(pass_restored_names)

    # if not pass_restored_names:
    #     break

    return terminator_comment_pattern.sub("", text), restored_names


def process_proof(
    index: int,
    proof: Proof,
    text: str,
    filename_without_ext: str,
    theories_dir: Path,
) -> tuple[int, bool, Proof, tuple[str, Proof, str] | None]:
    upto_doc = file_upto(proof[3], text)
    after_doc = file_after(proof[3], text)
    commented_uptodoc = comment_proofs_until(upto_doc, index)
    commented_afterdoc = comment_proofs(after_doc)
    test_doc = commented_uptodoc + commented_afterdoc

    rocq_sub = run_rocq_on_text(
        test_doc,
        filename_without_ext,
        theories_dir,
        capture_output=True,
    )

    if rocq_sub.returncode == 0:
        return index, True, proof, None

    proof_prop = proof[0]
    stderr_clean = remove_warning_blocks(rocq_sub.stderr.decode("utf-8"))
    error = (extract_proof_name(proof_prop), proof, stderr_clean)
    return index, False, proof, error


def collect_results(
    proof_results: list[tuple[bool, Proof, tuple[str, Proof, str] | None] | None],
) -> tuple[list[Proof], list[tuple[str, Proof, str]]]:
    unsafe_proofs: list[Proof] = []
    errors: list[tuple[str, Proof, str]] = []

    for result in proof_results:
        if result is None:
            continue

        is_safe, proof, error = result
        if not is_safe:
            unsafe_proofs.append(proof)
            if error:
                errors.append(error)

    return unsafe_proofs, errors


def write_errors_log(
    filename: str,
    filename_without_ext: str,
    errors: list[tuple[str, Proof, str]],
) -> None:
    log_path = Path("logs") / f"{filename_without_ext}.logs"

    if not errors:
        if log_path.exists():
            log_path.unlink()
        return

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as f:
        f.write(f"{filename}:\n")
        for error in errors:
            error_str = textwrap.indent(f"{error[0]}: {error[2]}", "\t")
            f.write(error_str)

if __name__ == "__main__":
    args = parser.parse_args()
    filepath = Path(args.filename)
    filename = filepath.name
    filename_without_ext = filepath.with_suffix("").name
    filepath_parents =  list(filepath.parents)
    theories_dir = args.theories_dir or next(x for x in filepath_parents if x.name == "theories")
    if Path.exists(filepath):
        text = Path.read_text(filepath)

        proofs = extract_proofs(text)
        total_proofs = len(proofs)
        proof_results: list[tuple[bool, Proof, tuple[str, Proof, str] | None] | None] = [None] * total_proofs

        if total_proofs:
            configured_workers = args.workers if args.workers and args.workers > 0 else None
            worker_count = configured_workers or (os.cpu_count() or 1)
            worker_count = max(1, min(worker_count, total_proofs))

            update_progress(0, total_proofs)
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(
                        process_proof,
                        i,
                        proof,
                        text,
                        filename_without_ext,
                        theories_dir,
                    )
                    for i, proof in enumerate(proofs)
                ]

                completed = 0
                for future in as_completed(futures):
                    index, is_safe, proof, error = future.result()
                    proof_results[index] = (is_safe, proof, error)
                    completed += 1
                    update_progress(completed, total_proofs)

            sys.stderr.write("\n")

        unsafe_proofs, errors = collect_results(proof_results)
        unsafe_proofs_matches = [p[3] for p in unsafe_proofs]
        unsafe_comments = {
            proof[3].span(): UNSTABLE_GOAL_COMMENT
            for _, proof, error_text in errors
            if UNSTABLE_GOAL_ERROR in error_text
        }
        unsafe_commented_doc = comment_only_unsafe(text, unsafe_proofs_matches, unsafe_comments)
        if filename.startswith("Ch14"):
            unsafe_commented_doc, restored_names = cleanup_blacklisted_proofs(
                unsafe_commented_doc,
                filename_without_ext,
                theories_dir,
            )
            errors = [
                error
                for error in errors
                if error[0] not in restored_names
            ]
        
        write_errors_log(filename, filename_without_ext, errors)
        print(unsafe_commented_doc)
    else:
        exit(1)
