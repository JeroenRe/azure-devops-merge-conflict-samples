# Azure DevOps merge conflict samples

A small repository that produces **one pull request with 13 hard merge conflicts**: different encodings, BOMs, line
endings, non-ASCII text, a 2 MB lockfile, binary files, a Git LFS pointer, a rename/rename, an edit/delete and an
add/add.

Use it to test any merge conflict tool for Azure DevOps **before you trust it with real code**: the web UI, a Git
client, an IDE or an extension. You resolve the conflicts with the tool you want to test, then `verify.py` checks the
result against both original sides, byte for byte, and tells you which case broke.

The script only looks at the result. It does not care which tool produced it, and nothing in this repository is specific
to one product.

## The 13 conflicts

Merging `feature/sample-conflicts` into `main` conflicts on every one of these (checked with plain git):

| # | Case | Path | What is tricky |
|---|------|------|----------------|
| 01 | `utf8-bom-crlf` | `encoding/Greeting.cs` | UTF-8 **with BOM**, CRLF, contains `Grüße`, `€`, `naïve`. The BOM and the CRLFs must survive. |
| 02 | `utf16le-bom-crlf` | `encoding/Resources.rc` | **UTF-16 LE** with BOM, CRLF (a typical Visual Studio resource file), contains `Größe`, `€`. Git sees NUL bytes and treats it as binary, so a tool has to recognise the encoding itself. |
| 03 | `windows1252-crlf` | `encoding/legacy.ini` | **Windows-1252** (ANSI), CRLF, contains `é`, `ß`, `€` (0x80), `ü`. Not valid UTF-8: reading it as UTF-8 and saving it again destroys these bytes. |
| 04 | `ascii-crlf` | `line-endings/build.cmd` | ASCII, CRLF. Every line must stay CRLF. |
| 05 | `ascii-lf` | `line-endings/deploy.sh` | ASCII, LF. A CR in a shell script breaks it (`/usr/bin/env: 'bash\r': No such file or directory`). |
| 06 | `ascii-mixed-eol` | `line-endings/mixed.txt` | ASCII with **mixed** CRLF and LF in blocks of five lines. The conflict is in the middle and crosses a CRLF/LF boundary. Each line must keep its own ending. |
| 07 | `utf8-unicode` | `unicode/strings.json` | UTF-8 without BOM, LF. Hebrew `שלום`, Arabic `مرحبا`, Chinese `你好`, Japanese `こんにちは`, Czech `č ř`, and an emoji `🚀` (outside the BMP). |
| 08 | `large-json-lockfile` | `lockfile/package-lock.json` | A valid npm lockfile of about 2 MB with **two separate conflicting hunks** (two packages with different versions on each branch). Both sides, and the result, must be valid JSON. |
| 09 | `binary-png` | `assets/logo.png` | A binary PNG that differs on both branches. It cannot be merged; you can only pick a side. It must come out byte-identical. |
| 10 | `lfs-pointer` | `assets/design.psd` | A Git LFS pointer file (see below) that differs on both branches. Must stay a valid pointer of one side. |
| 11 | `rename-rename` | `src/Helper.cs` | Renamed to `src/Helpers.cs` on main and to `src/MathHelper.cs` on feature. |
| 12 | `edit-delete` | `src/Legacy.cs` | Deleted on main, modified on feature. |
| 13 | `add-add` | `docs/notes.md` | Added on both branches with different content (UTF-8, contains `—`, `é`, `ë`); there is no common base. |

Each `mixed.txt` line starts with its number and its expected ending (`[CRLF]` or `[LF]`), so you can see at a glance
what a tool did to it.

## How to use it

1. Create a free Azure DevOps organization, or use a throwaway test project. Do not use a real project.
2. **Repos → Import repository → Git**, clone URL:
   `https://github.com/JeroenRe/azure-devops-merge-conflict-samples.git`
   Check that both branches, `main` and `feature/sample-conflicts`, arrived.
3. Create a pull request from `feature/sample-conflicts` into `main`. It reports conflicts in the files above (Azure
   DevOps may count the rename/rename and edit/delete differently from git).
4. Resolve the conflicts with the tool you want to test. Resolve them the way you normally would; the check does not
   care whether you took main's side, feature's side or a mix.
5. Verify the result. Clone your imported repository and run the script in the clone (Python 3.8 or newer and git, no
   other dependencies):

   ```
   git clone <url of your imported repo>
   cd <repo>
   git fetch origin refs/pull/<id>/merge:pr-merge
   python verify.py pr-merge
   ```

   (On Windows, `py verify.py pr-merge` works too.)

   The merge ref `refs/pull/<id>/merge` exists once the pull request has no conflicts left. If your tool commits the
   resolution to the source branch instead, fetch and verify that branch:

   ```
   git fetch origin
   python verify.py origin/feature/sample-conflicts
   ```

   You can also verify a copy of the result without git access to the PR: a folder, or a zip file (for example Azure
   DevOps **Repos → Files → ⋯ → Download as Zip** on the branch with the resolution). The script still needs the clone
   to read the two original sides.

   ```
   python verify.py path/to/folder
   python verify.py path/to/download.zip
   ```

**Do not complete the PR if you want to reuse it.** Completing it merges the result into `main`. To start over, delete
the pull request and the repository, or import the repository again into another project.

### What `verify.py` checks

The script compares the result with **both** sides, whichever you chose:

- Text files: the file exists, no conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) are left, the BOM is present
  exactly when the sides have one, the bytes decode strictly in the declared encoding, and the line endings are right
  (all CRLF, all LF, or for the mixed file: each line keeps the ending it has in the sides). Any line that appears on
  a side must come out unchanged, and characters that both sides contain must still be there. Typical damage such as
  replacement characters, mojibake or `???` is reported.
- `package-lock.json`: the text rules plus valid JSON.
- `logo.png` and `design.psd`: byte-identical to one of the sides; the pointer must also be a valid LFS pointer.
- Rename/rename: the old name must be gone and at least one of the two new names must exist, with valid content.
- Edit/delete: deleted, or kept with valid content.
- Add/add: the text rules against both sides.

Output is one `PASS` or `FAIL` line per case plus a summary. The exit code is 0 only if all 13 cases pass. A `PASS` that
says `merged` means the file is neither side as a whole but is intact; the script cannot tell whether the merge is
semantically right, that is up to you.

Options: `--main <ref>` and `--feature <ref>` name the two sides. By default the script finds them itself, in
`origin/main` or `main` and in `origin/feature/sample-conflicts` or `feature/sample-conflicts`, so the comparison keeps
working after the resolution was committed to those branches.

## Notes

**The LFS pointer (`assets/design.psd`).** Git LFS replaces a large file by a small text file in the git repository:

```
version https://git-lfs.github.com/spec/v1
oid sha256:<64 hex characters>
size <bytes>
```

That text *is* the git object of an LFS file. So this sample commits the pointer as a normal blob, without an LFS filter
in `.gitattributes` and without a real LFS object: the conflict is exactly what a server or a tool sees. No LFS
server is needed, and no large file has to be downloaded. The `oid` and `size` values are made up.

**`* -text` in `.gitattributes`.** Git never converts line endings in this repository, on checkout or on commit, whatever
your `core.autocrlf` or the platform. The CRLF, LF and mixed files stay as they are in the git objects. If you copy
the files into another repository, keep this attribute (or add `-text` for these paths), otherwise git on Windows or
macOS may rewrite line endings behind your back.

**The lockfile is synthetic.** The package names and `integrity` hashes are generated; do not run `npm ci` on it. It is
only meant to have the size and shape of a real lockfile.

**Limits.** All 13 cases conflict with plain git (merge-ort, tested with git 2.43). Azure DevOps uses its own merge machinery and may list or
classify some of them differently. Passing these cases does not prove a tool is safe; failing one points at a concrete problem worth a closer look.

## Reporting problems

If a tool breaks one of these files, the case name tells the vendor exactly what to fix. Report the `FAIL` line, for
example:

```
FAIL 03 windows1252-crlf (encoding/legacy.ini): bytes are valid UTF-8, expected Windows-1252 (file re-saved as UTF-8?)
```

If you find a bug in a sample or in `verify.py`, or a false `FAIL`, open an issue.

## Disclosure

This repository was made by the developer of [Merge Conflict Resolver](https://jr-devtools.com/merge-conflict-resolver/),
an Azure DevOps extension for resolving pull request merge conflicts. It works with any resolver, and the check does not
know which tool you used. Contributions of new nasty cases are welcome through issues and pull requests.

MIT licensed, see `LICENSE`.
