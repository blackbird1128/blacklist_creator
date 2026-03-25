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
    unsafe_set = set(id(m) for m in unsafe_matches)

    def repl(match: re.Match[str]) -> str:
        if id(match) in unsafe_set:
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

if __name__ == "__main__":
    safe_proofs: list[Proof] = []
    unsafe_proofs: list[Proof] = []
    errors = []
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
                    errors.append((extract_proof_name(proof_prop), proof,rocq_sub.stderr))
            
        unsafe_proofs_matches = [p[2] for p in unsafe_proofs]
        unsafe_commented_doc = comment_only_unsafe(text,unsafe_proofs_matches)
        if errors:
            with open("logs/" + filename_without_ext + ".logs","w") as f:            
                f.write(f"{filename}:\n")
                for error in errors:
                    error_str = textwrap.indent(f"{error[0]}: {error[2].decode("utf-8")}","\t")
                    f.write(error_str)
        print(unsafe_commented_doc)
    else:
        print("provided path must exist")
        exit(1)
            
        
