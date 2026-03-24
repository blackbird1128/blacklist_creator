import argparse
import re
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(prog="blacklist maker",description="")
parser.add_argument('filename',type=str)  # pyright: ignore[reportUnusedCallResult]
pattern = r"((?:Lemma|Instance|Global Instance|Definition).*?)Proof\.(.*?)(?:Qed|Admitted|Abort|Defined)\."
regex_compiled: re.Pattern[str] = re.compile(pattern, re.DOTALL)


def extract_proofs (text: str) :
    matches: list[re.Match[str]] =  list(regex_compiled.finditer(text))
    return [(m.groups()[0].lstrip(),m.groups()[1],m) for m in matches]
    

def comment_proofs (text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        before = match.group(1)
        proof = match.group(2)
        return f"{before}Proof. (* {proof}*)Admitted."
    
    return regex_compiled.sub(repl, text)

def comment_proofs_until (text: str, n: int) -> str:
    def repl(match: re.Match[str]) -> str:
        before = match.group(1)
        proof = match.group(2)
        return f"{before}Proof. (* {proof}*)Admitted."

    return regex_compiled.sub(repl, text,count=n)

def comment_only_unsafe(text: str, unsafe_matches: list[re.Match[str]]) -> str:
    unsafe_set = set(id(m) for m in unsafe_matches)

    def repl(match: re.Match[str]) -> str:
        if id(match) in unsafe_set:
            before = match.group(1)
            proof = match.group(2)
            return f"{before}Proof. (* {proof} *)Admitted."
        else:
            return match.group(0)  # leave unchanged

    return regex_compiled.sub(repl, text)
    
def file_upto (m: re.Match[str],text: str):
   return text[0:m.end()]

def file_after (m: re.Match[str], text: str):
    return text[m.end():]

if __name__ == "__main__":
    safe_proofs = []
    unsafe_proofs = []
    args = parser.parse_args()
    filepath = Path(args.filename)
    filepath_parents =  list(filepath.parents)
    theories_dir = next(x for x in filepath_parents if x.name == "theories")
    print(theories_dir)
    if Path.exists(filepath):
        text = Path.read_text(filepath)

        proofs = extract_proofs(text)
        for i, proof in enumerate(proofs):
            upto_doc = file_upto(proof[2],text)
            after_doc = file_after(proof[2],text)
            commented_uptodoc = comment_proofs_until(upto_doc,i)
            commented_afterdoc = comment_proofs(after_doc)
            with tempfile.NamedTemporaryFile(mode="w", delete_on_close=True,suffix=".v") as fp:
                
                _ = fp.write(commented_uptodoc + commented_afterdoc)
                fp.flush()
                
                rocq_sub = subprocess.run(["rocq", "c", "-Q", theories_dir, "GeoCoq", "-w", "-ambiguous-paths", "-w", "notation-overridden",   fp.name],capture_output=True)
                if rocq_sub.returncode == 0:
                    safe_proofs.append(proof)
                else:
                    unsafe_proofs.append(proof)                    
                    print(rocq_sub.stderr)
                print(rocq_sub)
                
                
            print("****")
            
        print(unsafe_proofs)
        unsafe_proofs_matches = [p[2] for p in unsafe_proofs]
        unsafe_commented_doc = comment_only_unsafe(text,unsafe_proofs_matches)
        # print(unsafe_commented_doc)
    else:
        print("provided path must exist")
        exit(1)
            
        
