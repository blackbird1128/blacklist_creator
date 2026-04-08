import argparse
import re
from pathlib import Path
import subprocess
import tempfile
import textwrap

type Proof = tuple[str, str, re.Match[str]]

parser = argparse.ArgumentParser(prog="blacklist maker",description="")
parser.add_argument('filename',type=str)  # pyright: ignore[reportUnusedCallResult]
proof_pattern = r"((?:Goal|Lemma|Instance|Global Instance|Definition).*?)Proof\.(.*?)(?:Qed|Admitted|Abort|Defined)\."
proof_pattern_c : re.Pattern[str] = re.compile(proof_pattern, re.DOTALL)
name_pattern =  r"(?:Lemma|Instance|Global Instance|Definition)\s(.*?)\:"
name_pattern_c : re.Pattern[str] = re.compile(name_pattern,re.DOTALL)
file_line_pattern : re.Pattern[str] = re.compile(r'.*File ".*", line \d+, characters \d+-\d+:$')

def extract_proofs (text: str) -> list[Proof]:
    matches: list[re.Match[str]] =  list(proof_pattern_c.finditer(text))
    return [(m.groups()[0].lstrip(),m.groups()[1],m) for m in matches if not (m.groups()[1].strip().startswith("(*"))]

def extract_proof_name (proof_prop: str) -> str:
  matches: list[str] = name_pattern_c.findall(proof_prop)
  if matches == []:
      return "anonymous"
  else:
      return matches[0].strip()

def comment_proofs (text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        before = match.group(1)
        proof = match.group(2)
        return f"{before}Proof. (* {proof}*)Admitted."
    
    return proof_pattern_c.sub(repl, text)

def comment_proofs_until (text: str, n: int) -> str:
    def repl(match: re.Match[str]) -> str:
        before = match.group(1)
        proof = match.group(2)
        return f"{before}Proof. (* {proof}*)Admitted."

    return proof_pattern_c.sub(repl, text,count=n)

def comment_only_unsafe(text: str, unsafe_matches: list[re.Match[str]]) -> str:
    unsafe_set = set(m.span() for m in unsafe_matches)
    def repl(match: re.Match[str]) -> str:
        span = match.span()
        if span in unsafe_set:
            before = match.group(1)
            proof = match.group(2)
            return f"{before}Proof.\n(* blacklisted *)\n(* {proof} *)Admitted."
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

if __name__ == "__main__":
    safe_proofs: list[Proof] = []
    unsafe_proofs: list[Proof] = []
    errors: list[tuple[str, Proof, str]] = []
    args = parser.parse_args()
    filepath = Path(args.filename)
    filename = filepath.name
    filename_without_ext = filepath.with_suffix("").name
    filepath_parents =  list(filepath.parents)
    theories_dir = next(x for x in filepath_parents if x.name == "theories")

    if Path.exists(filepath):
        text = Path.read_text(filepath)

        proofs = extract_proofs(text)
        for i, proof in enumerate(proofs):
            upto_doc = file_upto(proof[2],text)
            after_doc = file_after(proof[2],text)
            commented_uptodoc = comment_proofs_until(upto_doc,i)
            commented_afterdoc = comment_proofs(after_doc)
            with tempfile.NamedTemporaryFile(mode="w", delete_on_close=True,suffix=".v",prefix=filename_without_ext) as fp:
                
                _ = fp.write(commented_uptodoc + commented_afterdoc)
                fp.flush()
                
                rocq_sub = subprocess.run(["rocq", "c", "-Q", str(theories_dir), "GeoCoq", "-w", "-ambiguous-paths", "-w", "notation-overridden",   fp.name],capture_output=True)
                if rocq_sub.returncode == 0 and rocq_sub.stdout == b"":
                    safe_proofs.append(proof)
                else:
                    proof_prop = proof[0]
                    unsafe_proofs.append(proof)                    
                    stderr_clean = remove_warning_blocks(rocq_sub.stderr.decode("utf-8"))
                    errors.append((extract_proof_name(proof_prop), proof, stderr_clean))
            
        unsafe_proofs_matches = [p[2] for p in unsafe_proofs]
        unsafe_commented_doc = comment_only_unsafe(text,unsafe_proofs_matches)
        if errors:
            with open("logs/" + filename_without_ext + ".logs","w") as f:            
                f.write(f"{filename}:\n")
                for error in errors:
                    error_str = textwrap.indent(f"{error[0]}: {error[2]}","\t")
                    f.write(error_str)
        print(unsafe_commented_doc)
    else:
        print("provided path must exist")
        exit(1)
