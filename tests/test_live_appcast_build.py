#!/usr/bin/env python3
"""live_appcast_build.py reads the newest build an appcast lists; the classic
publication guards refuse a build older than the live feed's and fail closed
when it cannot be read; a successful publication never closes a failure
incident a newer commit reported."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "live_appcast_build.py"
WORKFLOW = (ROOT / ".github" / "workflows" / "auto-resume-nightly-notarization.yml").read_text(encoding="utf-8")

FEED = """<?xml version="1.0"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0"><channel>
<item><title>new</title><sparkle:version>2026102712345601</sparkle:version></item>
<item><title>old</title><enclosure url="x" sparkle:version="2026102612345601"/></item>
</channel></rss>
"""


def run(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), source], capture_output=True, text=True, check=False)


def test_reads_the_newest_build() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as feed:
        feed.write(FEED)
    out = run(feed.name)
    assert out.returncode == 0 and out.stdout.strip() == "2026102712345601", out


def test_a_missing_feed_is_exit_3_and_a_server_error_exit_1() -> None:
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(404 if self.path.endswith("missing.xml") else 503)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        assert run(f"{base}/missing.xml").returncode == 3
        assert run(f"{base}/broken.xml").returncode == 1
    finally:
        server.shutdown()


def test_an_unreadable_or_empty_feed_is_unknown() -> None:
    assert run("/nonexistent/appcast.xml").returncode == 1
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as feed:
        feed.write("<rss><channel></channel></rss>")
    assert run(feed.name).returncode == 1


def guard_script(marker: str) -> str:
    """The run: block of the auto-resume step whose script contains marker."""
    import yaml

    document = yaml.safe_load(WORKFLOW)
    for job in document["jobs"].values():
        for step in job.get("steps", []):
            if marker == step.get("name") or marker in str(step.get("run", "")):
                return step["run"]
    raise AssertionError(f"no step contains {marker!r}")


def run_guard(script: str, helper_rc: int, helper_out: str, env: dict) -> subprocess.CompletedProcess[str]:
    """Run a guard block with a stub live_appcast_build.py that answers (rc, out) for https URLs."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "scripts" / "ci").mkdir(parents=True)
        (work / "scripts" / "ci" / "live_appcast_build.py").write_text(
            "import sys\n"
            f"if sys.argv[1].startswith('https://'):\n    print({helper_out!r}) if {helper_rc} == 0 else None\n    sys.exit({helper_rc})\n"
            "print(open(sys.argv[1]).read().strip())\n", encoding="utf-8")
        # The release writer: records that it ran, and with what.
        (work / "scripts" / "ci" / "publish-release-assets.py").write_text(
            "import sys\nprint('PUBLISHED', *sys.argv[1:])\n", encoding="utf-8")
        (work / "nightly-deltas").mkdir()
        (work / "nightly-deltas" / "appcast-arm64.xml").write_text(env.get("OWN", "100"), encoding="utf-8")
        (work / "nightly-deltas" / "x.delta").write_text("d", encoding="utf-8")
        (work / "gh").write_text("#!/bin/sh\necho \"$*\" >> \"$GH_LOG\"\n[ \"$1\" = api ] && echo \"$SOURCE_HEAD_SHA\"\nexit 0\n", encoding="utf-8")
        (work / "gh").chmod(0o755)
        (work / "python3").write_text(f"#!/bin/sh\nexec {sys.executable} \"$@\"\n", encoding="utf-8")
        (work / "python3").chmod(0o755)
        out = work / "out"
        out.write_text("", encoding="utf-8")
        full_env = {"PATH": f"{work}:/usr/bin:/bin", "GITHUB_OUTPUT": str(out), "GITHUB_ENV": str(work / "env"),
                    "RUNNER_TEMP": str(work), "GH_LOG": str(work / "gh.log"), "RELEASE_TAG": "nightly", "GITHUB_REPOSITORY": "o/r",
                    "SOURCE_HEAD_SHA": "a" * 40, **env}
        result = subprocess.run(["bash", "-c", script], cwd=work, env=full_env, capture_output=True, text=True, check=False)
        result.stdout += "\nOUTPUT:" + out.read_text(encoding="utf-8")
        result.stdout += "\nGH:" + ((work / "gh.log").read_text(encoding="utf-8") if (work / "gh.log").exists() else "")
        return result


def test_the_delta_republish_fails_closed_on_an_unread_feed() -> None:
    script = guard_script("Skipping stale delta result: the live")
    # The live feed serves this build: the deltas go out.
    ok = run_guard(script, 0, "100", {"OWN": "100"})
    assert ok.returncode == 0 and "publish=true" in ok.stdout and "--replace-feeds" in ok.stdout, ok
    # A newer build is live, or the feed cannot be read: nothing is written.
    for rc, out in ((0, "101"), (1, ""), (3, "")):
        skipped = run_guard(script, rc, out, {"OWN": "100"})
        assert skipped.returncode == 0 and "publish=false" in skipped.stdout and "--replace-feeds" not in skipped.stdout, (rc, skipped)


def test_the_publish_guard_refuses_an_older_build_and_an_unread_feed() -> None:
    script = guard_script("Reject stale continuation before publication")
    live = script[script.index("# Fail closed: only a 404"):]
    live = live[:live.index("if grep -Fxq 'already_published=true'")]
    prelude = "set -euo pipefail\n: > \"$RUNNER_TEMP/publication-guard\"\n"
    newer = run_guard(prelude + live + "grep -Fxq already_published=true \"$RUNNER_TEMP/publication-guard\" && echo REFUSED\n", 0, "200", {"NIGHTLY_BUILD": "100"})
    assert "REFUSED" in newer.stdout, newer
    older = run_guard(prelude + live + "grep -Fxq already_published=true \"$RUNNER_TEMP/publication-guard\" || echo GOES\n", 0, "50", {"NIGHTLY_BUILD": "100"})
    assert "GOES" in older.stdout, older
    first = run_guard(prelude + live + "echo GOES\n", 3, "", {"NIGHTLY_BUILD": "100"})
    assert "GOES" in first.stdout, first
    unread = run_guard(prelude + live + "echo GOES\n", 1, "", {"NIGHTLY_BUILD": "100"})
    assert unread.returncode != 0 and "GOES" not in unread.stdout, unread


def test_a_close_never_takes_a_newer_commits_incident() -> None:
    harness = r"""
const { covers, failedShas } = await import(process.env.MODULE);
const order = ['a', 'b', 'c'].map((c) => c.repeat(40));  // a < b < c in history
const github = {
  paginate: async () => JSON.parse(process.env.COMMENTS),
  rest: { issues: { listComments: Symbol() }, repos: { compareCommitsWithBasehead: async ({ basehead }) => {
    const [base, head] = basehead.split('...');
    const d = order.indexOf(head) - order.indexOf(base);
    return { data: { status: d > 0 ? 'ahead' : d === 0 ? 'identical' : 'behind' } };
  } } },
};
const issue = { number: 1, body: `cmux NIGHTLY run x failed on ${order[0]} (main) in: build.` };
console.log(JSON.stringify({ covers: await covers({ github, owner: 'o', repo: 'r', issue, sha: process.env.SHA }), shas: failedShas([issue.body]) }));
"""
    module = ROOT / "scripts" / "ci" / "nightly_failure_issue.mjs"

    def decide(sha: str, comments: list[str]) -> dict:
        import json
        import os
        out = subprocess.run(["node", "--input-type=module", "-e", harness], capture_output=True, text=True, check=True,
                             env={**os.environ, "MODULE": str(module), "SHA": sha,
                                  "COMMENTS": json.dumps([{"body": c} for c in comments])})
        return json.loads(out.stdout)

    later_failure = f"cmux NIGHTLY run y failed on {'c' * 40} (main) in: build."
    assert decide("b" * 40, [])["covers"] is True
    assert decide("b" * 40, [later_failure])["covers"] is False
    assert decide("c" * 40, [later_failure])["covers"] is True


def test_the_close_steps_use_the_coverage_check() -> None:
    nightly = (ROOT / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
    assert nightly.count("nightly_failure_issue.mjs") >= 2, "nightly.yml's close job must check out and use the helper"
    assert "if (!(await covers({ github, owner, repo, issue, sha: process.env.SOURCE_HEAD_SHA, core }))) continue;" in WORKFLOW
    assert "if (!(await covers({ github, owner, repo, issue, sha: process.env.HEAD_SHA, core }))) continue;" in nightly


if __name__ == "__main__":
    for name, value in list(globals().items()):
        if name.startswith("test_"):
            value()
    print("PASS: live appcast build guard")
