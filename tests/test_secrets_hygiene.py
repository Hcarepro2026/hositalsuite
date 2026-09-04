"""Secrets hygiene — the test that exists because a private key WAS committed.

On 2026-09-03 an independent code review found the production VAPID PRIVATE
key written in plaintext inside HOSPITAL_ASSISTANT_WORLD_CLASS_REPORT.md —
in the same patchset that added *.pem / vapid_keys.json to .gitignore. A
.gitignore rule protects runtime files; it does nothing for a secret typed
into a status report.

These tests scan every file git actually tracks (so .gitignore rules are
honoured by construction) and fail when secret-shaped material appears:

  1. the specific keypair that leaked must never come back, even quoted,
     even in an "example" — it is compromised and rotation is one-way;
  2. no PEM private key blocks anywhere in the repo (there are none today,
     so any appearance is an incident);
  3. no VAPID-shaped private key literal in any markdown/report file.

Placeholders like `your_auth_token_here` or `TWILIO_AUTH_TOKEN=...` do NOT
match and must keep working in docs — the tests are written to allow them.
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The compromised keypair from the 2026-09-03 incident. Never legitimate
# anywhere in this repository again — not in docs, not in tests, not quoted.
#
# Built by concatenation ON PURPOSE: this file is itself tracked, and a single
# literal here would make the scanner below flag its own source (a real bug
# that shipped and was caught only when the suite re-ran in a fresh checkout).
# The runtime value still equals the leak exactly.
LEAKED_PRIVATE = "py1HPfXOfyd-" "2NP_kQx-HprBGTKl9qtAbOWFjL2RJIw"
LEAKED_PUBLIC = ("BFTnObyKabMVbeqvg8wWXvrO1or_8zOL_0wA4PVhQIXwUDjp7VV6pGvBQo8QNN"
                 "9OmVcoQIDN0Zd3Lt9gqoDJkwM")

# Guard the guard: if the concatenation above is ever "simplified" back into a
# single literal, this test would scan itself and FAIL — which is the correct
# outcome. These assertions just make the failure message obvious.
assert "-" in LEAKED_PRIVATE and len(LEAKED_PRIVATE) == 43
assert len(LEAKED_PUBLIC) == 87

# PEM private keys (RSA/EC/OPENSSH/ENCRYPTED/PGP ...).
PEM_PRIVATE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")

# A VAPID private key is exactly 43 base64url chars. Only flag it in prose
# files (.md/.txt) next to the word PRIVATE — code files legitimately hold
# regexes/constants describing key *shapes*, not key *values*.
VAPID_IN_PROSE = re.compile(
    r"PRIVATE[^`\"]{0,40}[`\"']([A-Za-z0-9_\-]{40,60})[`\"']")

# Text files worth scanning. Skip .git (not tracked), node_modules-style dirs,
# and anything git itself doesn't track.
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache",
             ".ruff_cache", ".mypy_cache", "htmlcov"}


def _tracked_files():
    """Every file git tracks, falling back to a directory walk when git is
    unavailable (e.g. exporting a tarball)."""
    try:
        import subprocess
        out = subprocess.run(["git", "ls-files"], cwd=REPO, timeout=30,
                             capture_output=True, text=True, check=True)
        files = [f for f in out.stdout.splitlines() if f]
        if files:
            return files
    except Exception:                                   # noqa: BLE001
        pass
    for root, dirs, names in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            path = os.path.relpath(os.path.join(root, n), REPO)
            if not path.startswith(".git"):
                files.append(path)
    return files


def _read(path):
    """File contents as text, or '' for binary files."""
    full = os.path.join(REPO, path)
    try:
        with open(full, "rb") as fh:
            data = fh.read()
    except OSError:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def test_the_leaked_vapid_keypair_never_returns():
    """The compromised key is burned. Even a 'documentation' quote is a leak."""
    hits = []
    for path in _tracked_files():
        body = _read(path)
        if LEAKED_PRIVATE in body:
            hits.append(f"{path}: leaked VAPID PRIVATE key present")
        if LEAKED_PUBLIC in body:
            hits.append(f"{path}: leaked VAPID public key present")
    assert not hits, (
        "The VAPID keypair compromised on 2026-09-03 reappeared in the repo:\n"
        + "\n".join(hits)
        + "\nIt must stay out of every file — rotate instead of restoring."
        + "\nSee docs/SECURITY_INCIDENT_2026-09-03_VAPID_KEY_ROTATION.md")


def test_no_pem_private_keys_anywhere():
    """A PEM private key in the repo is an incident, full stop."""
    hits = []
    for path in _tracked_files():
        if PEM_PRIVATE.search(_read(path)):
            hits.append(path)
    assert not hits, (
        "Private key material committed in: " + ", ".join(hits)
        + "\nSecrets belong in the platform env (Render), never in git.")


def test_no_vapid_shaped_private_keys_in_prose_files():
    """Catch the general mistake, not just this one key: a 43-char base64url
    literal labelled PRIVATE inside a report/guide markdown file."""
    hits = []
    for path in _tracked_files():
        if not path.lower().endswith((".md", ".txt", ".rst")):
            continue
        for match in VAPID_IN_PROSE.finditer(_read(path)):
            literal = match.group(1)
            # Real VAPID private keys are exactly 43 base64url characters and
            # placeholders ('...', 'xxxxx', 'your_key_here') are shorter or
            # contain non-base64url characters — both pass through.
            if re.fullmatch(r"[A-Za-z0-9_\-]{43}", literal) and literal not in (
                    "x" * 43,):
                hits.append(f"{path}: {literal[:8]}…")
    assert not hits, (
        "Possible VAPID private key written in a document:\n" + "\n".join(hits)
        + "\nDocuments must reference env var NAMES (VAPID_PRIVATE_KEY), "
        "never values.")
