#!/usr/bin/env python3
"""Check the result of resolving the sample pull request, byte for byte.

The sample repository contains 13 files that conflict when
feature/sample-conflicts is merged into main (see README.md). This script
checks a resolved result against BOTH original sides, no matter which side (or
which mix of both) you chose. It checks that encodings, BOMs, line endings and
non-ASCII text survived and that no conflict markers are left.

Requires Python 3.8+ and git, nothing else. Run it inside a clone of this
repository, or inside a clone of the Azure DevOps repository you imported it
into: the two original sides are always read from git.

Usage examples:

  # A commit-ish with the resolved result, e.g. the PR merge ref ...
  git fetch origin refs/pull/<id>/merge:pr-merge
  python verify.py pr-merge

  # ... or the source branch, after the resolution was committed to it
  git fetch origin
  python verify.py origin/feature/sample-conflicts

  # A folder or a zip file with a copy of the merge result (for example the
  # "Download as Zip" of Azure DevOps). A single top-level folder inside the
  # zip is stripped automatically.
  python verify.py path/to/folder
  python verify.py path/to/download.zip

  # Name the two sides yourself (default: origin/main or main, and
  # origin/feature/sample-conflicts or feature/sample-conflicts)
  python verify.py pr-merge --main origin/main --feature origin/feature/sample-conflicts

How the sides are found: unless you pass --main/--feature, the script looks for
the original commits "Change samples on main" and "Change samples on feature"
in the history of the default refs. That way the check still compares against
the ORIGINAL sides after the resolution was committed to the source branch or
after the pull request was completed. A ref you pass explicitly is used as is.

Output: one PASS/FAIL line per case, then a summary. Exit code 0 only if all
13 cases pass, 1 if at least one case fails, 2 if the script cannot run.
Output is plain ASCII.

The checks are heuristics on top of exact comparisons: they tell you that a
file is intact, not that the merge is semantically right.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile

MAIN_SUBJECT = "Change samples on main"
FEATURE_SUBJECT = "Change samples on feature"
MAIN_REFS = ("origin/main", "main")
FEATURE_REFS = ("origin/feature/sample-conflicts", "feature/sample-conflicts")

CODECS = {"ascii": "ascii", "utf-8": "utf-8", "utf-16-le": "utf-16-le", "cp1252": "cp1252"}
ENC_NAMES = {"ascii": "ASCII", "utf-8": "UTF-8", "utf-16-le": "UTF-16 LE", "cp1252": "Windows-1252"}
BOM_BYTES = {"utf-8": b"\xef\xbb\xbf", "utf-16-le": b"\xff\xfe"}
KNOWN_BOMS = (
    (b"\xef\xbb\xbf", "UTF-8 BOM (EF BB BF)"),
    (b"\xff\xfe", "UTF-16 LE BOM (FF FE)"),
    (b"\xfe\xff", "UTF-16 BE BOM (FE FF)"),
)
EOL_NAMES = {"\r\n": "CRLF", "\n": "LF", "": "no line ending"}

# Git conflict markers (also diff3 style). A line that is also present in one of
# the sides is never reported, so a legitimate "=======" line would not be flagged.
MARKER_RE = re.compile(r"^(?:<<<<<<<|>>>>>>>|\|\|\|\|\|\|\|)(?: .*)?$|^=======$")

# Sequences that point to damaged text. They are only reported when they are
# not present in the text of either side.
SUSPICIOUS = (
    ("\ufffd", "a replacement character (U+FFFD): bytes were lost while decoding"),
    ("\ufeff", "a stray BOM character (U+FEFF) inside the text"),
    ("\x00", "a NUL character (wrong encoding?)"),
    ("\u00c3", "U+00C3, typical for UTF-8 text read as Windows-1252"),
    ("\u00c2", "U+00C2, typical for UTF-8 text read as Windows-1252"),
    ("\u00e2\u20ac", "U+00E2 U+20AC, typical for a UTF-8 euro sign read as Windows-1252"),
    ("\u00e2\u201a", "U+00E2 U+201A, typical for a UTF-8 euro sign read as Windows-1252"),
    ("??", "'??' (non-ASCII characters replaced by question marks?)"),
)

POINTER_RE = re.compile(
    rb"\Aversion https://git-lfs\.github\.com/spec/v1\noid sha256:[0-9a-f]{64}\nsize [0-9]+\n\Z"
)


# --------------------------------------------------------------------------
# The manifest: the 13 cases
# --------------------------------------------------------------------------

class Spec(object):
    """What a text file must look like: encoding, BOM and line endings."""

    def __init__(self, enc, eol, bom=False, json_valid=False, not_utf8=False):
        self.enc = enc
        self.eol = eol  # "crlf", "lf" or "mixed"
        self.bom = bom
        self.json_valid = json_valid
        self.not_utf8 = not_utf8  # the file must NOT be valid UTF-8 (ANSI file)

    def describe(self):
        text = ENC_NAMES[self.enc] + (" with BOM" if self.bom else "")
        return "%s, %s" % (text, self.eol.upper() if self.eol != "mixed" else "mixed line endings")


class Case(object):
    def __init__(self, num, name, kind, path, spec=None):
        self.num = num
        self.name = name
        self.kind = kind  # text, binary, pointer, rename, editdelete
        self.path = path
        self.spec = spec


RENAME_OLD = "src/Helper.cs"
RENAME_MAIN = "src/Helpers.cs"
RENAME_FEATURE = "src/MathHelper.cs"
TEXT_SPEC_SRC = Spec("utf-8", "lf")

CASES = [
    Case(1, "utf8-bom-crlf", "text", "encoding/Greeting.cs", Spec("utf-8", "crlf", bom=True)),
    Case(2, "utf16le-bom-crlf", "text", "encoding/Resources.rc", Spec("utf-16-le", "crlf", bom=True)),
    Case(3, "windows1252-crlf", "text", "encoding/legacy.ini", Spec("cp1252", "crlf", not_utf8=True)),
    Case(4, "ascii-crlf", "text", "line-endings/build.cmd", Spec("ascii", "crlf")),
    Case(5, "ascii-lf", "text", "line-endings/deploy.sh", Spec("ascii", "lf")),
    Case(6, "ascii-mixed-eol", "text", "line-endings/mixed.txt", Spec("ascii", "mixed")),
    Case(7, "utf8-unicode", "text", "unicode/strings.json", Spec("utf-8", "lf")),
    Case(8, "large-json-lockfile", "text", "lockfile/package-lock.json", Spec("utf-8", "lf", json_valid=True)),
    Case(9, "binary-png", "binary", "assets/logo.png"),
    Case(10, "lfs-pointer", "pointer", "assets/design.psd"),
    Case(11, "rename-rename", "rename", RENAME_OLD),
    Case(12, "edit-delete", "editdelete", "src/Legacy.cs", TEXT_SPEC_SRC),
    Case(13, "add-add", "text", "docs/notes.md", Spec("utf-8", "lf")),
]


# --------------------------------------------------------------------------
# Sources: where the bytes of a file come from
# --------------------------------------------------------------------------

class GitSource(object):
    """Files of one commit, read with `git cat-file`."""

    def __init__(self, repo, rev):
        self.repo = repo
        self.rev = rev
        self.cache = {}

    def read(self, path):
        if path not in self.cache:
            proc = subprocess.run(
                ["git", "cat-file", "blob", "%s:%s" % (self.rev, path)],
                cwd=self.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.cache[path] = proc.stdout if proc.returncode == 0 else None
        return self.cache[path]


class FolderSource(object):
    """Files in a folder. Names are matched case-sensitively, also on Windows."""

    def __init__(self, root):
        self.root = root

    def read(self, path):
        current = self.root
        parts = path.split("/")
        for index, part in enumerate(parts):
            try:
                names = os.listdir(current)
            except OSError:
                return None
            if part not in names:
                return None
            current = os.path.join(current, part)
            if index < len(parts) - 1 and not os.path.isdir(current):
                return None
        if not os.path.isfile(current):
            return None
        with open(current, "rb") as handle:
            return handle.read()


class ZipSource(object):
    """Files in a zip. A single top-level folder is stripped. Nothing is extracted."""

    def __init__(self, path):
        self.archive = zipfile.ZipFile(path)
        entries = {}
        for info in self.archive.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/"):
                continue
            entries[name] = info
        firsts = set(name.split("/")[0] for name in entries)
        self.stripped = None
        if len(firsts) == 1 and all("/" in name for name in entries):
            self.stripped = firsts.pop()
            prefix = self.stripped + "/"
            entries = dict((name[len(prefix):], info) for name, info in entries.items())
        self.entries = entries

    def read(self, path):
        info = self.entries.get(path)
        if info is None:
            return None
        return self.archive.read(info)


# --------------------------------------------------------------------------
# Text checks
# --------------------------------------------------------------------------

def split_lines(text):
    """Split on LF only. Returns a list of (content, ending); ending is CRLF, LF or ''."""
    lines = []
    pos = 0
    size = len(text)
    while pos < size:
        end = text.find("\n", pos)
        if end < 0:
            lines.append((text[pos:], ""))
            break
        if end > pos and text[end - 1] == "\r":
            lines.append((text[pos:end - 1], "\r\n"))
        else:
            lines.append((text[pos:end], "\n"))
        pos = end + 1
    return lines


def short(text, limit=24):
    text = ascii(text)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def codepoints(chars, limit=8):
    chars = sorted(chars)
    shown = " ".join("U+%04X" % ord(c) for c in chars[:limit])
    if len(chars) > limit:
        shown += " (+%d more)" % (len(chars) - limit)
    return shown


def decode_text(data, spec):
    """Strict decode in the declared encoding. Returns (text or None, problems)."""
    problems = []
    body = data
    if spec.bom:
        bom = BOM_BYTES[spec.enc]
        if data.startswith(bom):
            body = data[len(bom):]
        else:
            wanted = [name for prefix, name in KNOWN_BOMS if prefix == bom][0]
            found = [name for prefix, name in KNOWN_BOMS if data.startswith(prefix)]
            message = "%s missing" % wanted
            if found:
                message += ", the file starts with a %s instead" % found[0]
            elif spec.enc == "utf-16-le" and b"\x00" not in data[:200]:
                problems.append(message + " (the file looks like 8-bit text: converted from UTF-16?)")
                return None, problems
            problems.append(message)
    else:
        for prefix, name in KNOWN_BOMS:
            if data.startswith(prefix):
                problems.append("unexpected %s at the start of the file" % name)
                if prefix == b"\xef\xbb\xbf":
                    body = data[len(prefix):]
                break
    try:
        text = body.decode(CODECS[spec.enc])
    except UnicodeDecodeError as exc:
        if spec.enc == "ascii":
            problems.append("not plain ASCII: byte 0x%02X at offset %d" % (body[exc.start], exc.start))
        else:
            problems.append("not valid %s: %s at byte %d" % (ENC_NAMES[spec.enc], exc.reason, exc.start))
        return None, problems
    return text, problems


def check_text(data, spec, sides):
    """Apply the text rules to `data`. `sides` maps "main"/"feature" to the bytes of that
    side's version. Returns (problems, info)."""
    if not data:
        return ["file is empty"], ""
    problems = []
    text, found = decode_text(data, spec)
    problems.extend(found)
    if text is None:
        return problems, ""

    side_text = {}
    for name in sorted(sides):
        decoded, _ = decode_text(sides[name], spec)
        if decoded is not None:
            side_text[name] = decoded
    side_lines = dict((name, split_lines(value)) for name, value in side_text.items())
    endings = {}
    for lines in side_lines.values():
        for content, ending in lines:
            endings.setdefault(content, set()).add(ending)

    # Encoding: an ANSI file must not have been re-saved as UTF-8.
    if spec.not_utf8 and not data.isascii():
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            problems.append("bytes are valid UTF-8, expected %s (file re-saved as UTF-8?)" % ENC_NAMES[spec.enc])

    lines = split_lines(text)

    # Conflict markers.
    marked = [(i, c) for i, (c, _) in enumerate(lines, 1) if MARKER_RE.match(c) and c not in endings]
    if marked:
        problems.append("conflict marker left on line %d (%s)%s" % (
            marked[0][0], short(marked[0][1]), " and %d more" % (len(marked) - 1) if len(marked) > 1 else ""))

    # Line endings.
    problems.extend(check_eol(lines, spec.eol, endings))

    # Damaged text introduced by the resolution.
    all_side_text = "".join(side_text.values())
    for pattern, meaning in SUSPICIOUS:
        if pattern in text and pattern not in all_side_text:
            problems.append("contains %s" % meaning)

    # Decomposed accents (NFD) are what some file systems and tools produce from precomposed text.
    if not text.isascii():
        marks = set(c for c in text if 0x300 <= ord(c) <= 0x36F) - set(all_side_text)
        if marks:
            problems.append("contains combining accent characters (%s): decomposed Unicode (NFD)?" % codepoints(marks, 3))

    # Non-ASCII characters that both sides contain must still be there.
    if side_text:
        sets = [set() if value.isascii() else set(c for c in value if ord(c) > 127) for value in side_text.values()]
        missing = set.intersection(*sets) - set(text)
        if missing:
            problems.append("characters present in both sides are missing: %s" % codepoints(missing))

    # JSON.
    if spec.json_valid:
        try:
            json.loads(text)
        except ValueError as exc:
            problems.append("not valid JSON: %s" % exc)

    # Where do the lines come from?
    sets_by_side = dict((name, set(c for c, _ in value)) for name, value in side_lines.items())
    main_set = sets_by_side.get("main", set())
    feature_set = sets_by_side.get("feature", set())
    only_main = only_feature = new = 0
    for content, _ in lines:
        in_main, in_feature = content in main_set, content in feature_set
        if in_main and not in_feature:
            only_main += 1
        elif in_feature and not in_main:
            only_feature += 1
        elif not in_main and not in_feature:
            new += 1
    info = "%s; lines only from main: %d, only from feature: %d, new: %d" % (
        spec.describe(), only_main, only_feature, new)
    return problems, info


def check_eol(lines, eol, endings):
    problems = []
    if lines and lines[-1][1] == "":
        problems.append("the last line has no line ending")
    if eol == "crlf":
        bad = [i for i, (c, e) in enumerate(lines, 1) if e == "\n" or "\r" in c]
        if bad:
            problems.append("line endings are not all CRLF: %d line(s) differ, first on line %d" % (len(bad), bad[0]))
    elif eol == "lf":
        bad = [i for i, (c, e) in enumerate(lines, 1) if e == "\r\n" or "\r" in c]
        if bad:
            problems.append("line endings are not all LF: %d line(s) contain CR, first on line %d" % (len(bad), bad[0]))
    else:  # mixed: every line known from a side keeps the ending it has there
        bad = []
        for i, (c, e) in enumerate(lines, 1):
            if "\r" in c:
                bad.append((i, "contains a stray CR"))
            elif c in endings and e != "" and e not in endings[c]:
                expected = "/".join(sorted(EOL_NAMES[x] for x in endings[c]))
                bad.append((i, "ends with %s, expected %s" % (EOL_NAMES[e], expected)))
        if bad:
            problems.append("%d line(s) lost their original ending, first: line %d %s" % (len(bad), bad[0][0], bad[0][1]))
    return problems


def same_as_side(data, sides):
    return [name for name in ("main", "feature") if sides.get(name) == data]


def verdict(problems, data, sides, info):
    if problems:
        return False, "; ".join(problems[:3]) + (" (+%d more)" % (len(problems) - 3) if len(problems) > 3 else "")
    same = same_as_side(data, sides)
    if same:
        return True, "identical to " + " and ".join(same)
    return True, "merged (%s)" % info


# --------------------------------------------------------------------------
# The cases
# --------------------------------------------------------------------------

def side_bytes(main, feature, main_path, feature_path=None):
    sides = {}
    for name, source, path in (("main", main, main_path), ("feature", feature, feature_path or main_path)):
        data = source.read(path)
        if data is not None:
            sides[name] = data
    return sides


def run_text(case, result, main, feature):
    data = result.read(case.path)
    if data is None:
        return False, "file %s is missing from the result" % case.path
    sides = side_bytes(main, feature, case.path)
    problems, info = check_text(data, case.spec, sides)
    return verdict(problems, data, sides, info)


def run_binary(case, result, main, feature):
    data = result.read(case.path)
    if data is None:
        return False, "file %s is missing from the result" % case.path
    sides = side_bytes(main, feature, case.path)
    same = same_as_side(data, sides)
    if same:
        return True, "identical to " + " and ".join(same)
    hint = ""
    truncated = [name for name, value in sorted(sides.items()) if len(data) < len(value) and value.startswith(data)]
    if truncated:
        hint = ", looks like a truncated copy of " + " or ".join(truncated)
    return False, "not byte-identical to main (%d bytes) or feature (%d bytes); result has %d bytes%s" % (
        len(sides.get("main", b"")), len(sides.get("feature", b"")), len(data), hint)


def run_pointer(case, result, main, feature):
    data = result.read(case.path)
    if data is None:
        return False, "file %s is missing from the result" % case.path
    sides = side_bytes(main, feature, case.path)
    same = same_as_side(data, sides)
    if not POINTER_RE.match(data):
        why = "conflict markers left" if b"<<<<<<<" in data or b">>>>>>>" in data else "not a single valid LFS pointer"
        return False, "%s; a pointer is exactly 3 LF-terminated lines: version, oid sha256, size" % why
    if same:
        return True, "valid LFS pointer, identical to " + " and ".join(same)
    return False, "valid LFS pointer, but it matches neither main nor feature (a pointer must be one side's)"


def run_rename(case, result, main, feature):
    old_exists = result.read(RENAME_OLD) is not None
    found = {}
    for path in (RENAME_MAIN, RENAME_FEATURE):
        data = result.read(path)
        if data is not None:
            found[path] = data
    state = "%s %s, %s %s, %s %s" % (
        RENAME_OLD, "still exists" if old_exists else "gone",
        RENAME_MAIN, "exists" if RENAME_MAIN in found else "missing",
        RENAME_FEATURE, "exists" if RENAME_FEATURE in found else "missing")
    if old_exists:
        return False, "old name still exists (%s)" % state
    if not found:
        return False, "none of the new names exists (%s)" % state
    sides = {}
    main_data = main.read(RENAME_MAIN)
    feature_data = feature.read(RENAME_FEATURE)
    if main_data is not None:
        sides["main"] = main_data
    if feature_data is not None:
        sides["feature"] = feature_data
    notes = []
    for path in sorted(found):
        data = found[path]
        problems, info = check_text(data, TEXT_SPEC_SRC, sides)
        if problems:
            return False, "%s: %s" % (path, "; ".join(problems[:3]))
        same = same_as_side(data, sides)
        notes.append("%s %s" % (path, "identical to " + " and ".join(same) if same else "passes the text rules"))
    return True, "; ".join(notes) + ("; both names kept" if len(found) == 2 else "")


def run_editdelete(case, result, main, feature):
    data = result.read(case.path)
    if data is None:
        return True, "deleted"
    sides = {}
    feature_data = feature.read(case.path)
    if feature_data is not None:
        sides["feature"] = feature_data
    problems, info = check_text(data, case.spec, sides)
    ok, message = verdict(problems, data, sides, info)
    return ok, ("kept, " + message) if ok else message


RUNNERS = {
    "text": run_text,
    "binary": run_binary,
    "pointer": run_pointer,
    "rename": run_rename,
    "editdelete": run_editdelete,
}


def run_case(case, result, main, feature):
    try:
        return RUNNERS[case.kind](case, result, main, feature)
    except Exception as exc:  # keep going, report the case as failed
        return False, "internal error: %s: %s" % (type(exc).__name__, exc)


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def say(line=""):
    sys.stdout.write(line.encode("ascii", "replace").decode("ascii") + "\n")


def die(message):
    sys.stderr.write(message.encode("ascii", "replace").decode("ascii") + "\n")
    sys.exit(2)


def git_output(repo, *args):
    try:
        proc = subprocess.run(["git"] + list(args), cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        die("error: git was not found. Install git and make sure it is on the PATH.")
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


def find_repo():
    for folder in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        top = git_output(folder, "rev-parse", "--show-toplevel")
        if top:
            return top.strip()
    return None


def rev_parse(repo, ref):
    out = git_output(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    return out.strip() if out else None


def find_original(repo, ref, subject):
    """Newest commit with exactly this subject in the history of ref, or None."""
    out = git_output(repo, "log", "-n", "1000", "--format=%H%x09%s", ref)
    for line in (out or "").splitlines():
        sha, _, title = line.partition("\t")
        if title == subject:
            return sha
    return None


def resolve_side(repo, explicit, refs, subject, option):
    """Returns (sha, description)."""
    if explicit:
        sha = rev_parse(repo, explicit)
        if not sha:
            die("error: %s %r is not a commit in this repository." % (option, explicit))
        return sha, "%s (%s)" % (sha[:10], explicit)
    for ref in refs:
        tip = rev_parse(repo, ref)
        if not tip:
            continue
        original = find_original(repo, ref, subject)
        if original:
            return original, '%s "%s" (found in %s)' % (original[:10], subject, ref)
        return tip, "%s (tip of %s; commit \"%s\" not found in its history)" % (tip[:10], ref, subject)
    die("error: cannot find the %s side. Tried: %s. Fetch the branches (git fetch origin) or pass %s <ref>." % (
        option.lstrip("-"), ", ".join(refs), option))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="verify.py",
        description="Check the result of resolving the sample pull request against both sides, byte for byte.",
        epilog="Run inside a clone of the sample repository (or of the imported Azure DevOps repository).")
    parser.add_argument("target", help="commit-ish (e.g. pr-merge or origin/feature/sample-conflicts), "
                                       "a folder, or a .zip file with the merge result")
    parser.add_argument("--main", dest="main_ref", metavar="REF",
                        help="the main side (default: original commit found via origin/main or main)")
    parser.add_argument("--feature", dest="feature_ref", metavar="REF",
                        help="the feature side (default: original commit found via "
                             "origin/feature/sample-conflicts or feature/sample-conflicts)")
    args = parser.parse_args(argv)

    repo = find_repo()
    if repo is None:
        die("error: no git repository found. Run verify.py inside a clone of the sample repository: "
            "the two original sides are read from git.")

    target = args.target
    if os.path.isdir(target):
        result = FolderSource(target)
        result_text = "folder %s" % target
    elif os.path.isfile(target):
        if not zipfile.is_zipfile(target):
            die("error: %s is a file but not a zip file." % target)
        result = ZipSource(target)
        result_text = "zip file %s" % target
        if result.stripped:
            result_text += " (top-level folder %s stripped)" % result.stripped
    else:
        sha = rev_parse(repo, target)
        if not sha:
            die("error: %r is not a folder, a zip file or a commit in this repository. "
                "Did you run git fetch? For a pull request: git fetch origin refs/pull/<id>/merge:pr-merge" % target)
        result = GitSource(repo, sha)
        result_text = "commit %s (%s)" % (sha[:10], target)

    main_sha, main_text = resolve_side(repo, args.main_ref, MAIN_REFS, MAIN_SUBJECT, "--main")
    feature_sha, feature_text = resolve_side(repo, args.feature_ref, FEATURE_REFS, FEATURE_SUBJECT, "--feature")
    main_src = GitSource(repo, main_sha)
    feature_src = GitSource(repo, feature_sha)

    say("Result : %s" % result_text)
    say("Main   : %s" % main_text)
    say("Feature: %s" % feature_text)
    say()

    failed = 0
    for case in CASES:
        ok, message = run_case(case, result, main_src, feature_src)
        failed += 0 if ok else 1
        say("%s %02d %s (%s): %s" % ("PASS" if ok else "FAIL", case.num, case.name, case.path, message))

    # The sides must pass their own checks; if not, this is not the sample repository.
    for name, side in (("main", main_src), ("feature", feature_src)):
        for case in CASES:
            ok, message = run_case(case, side, main_src, feature_src)
            if not ok:
                say("WARNING: the %s side itself fails case %02d %s (%s). "
                    "Is this really a clone of the sample repository?" % (name, case.num, case.name, message))

    say()
    say("Summary: %d of %d cases passed, %d failed." % (len(CASES) - failed, len(CASES), failed))
    say("RESULT: " + ("ALL PASS" if not failed else "FAILED"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
