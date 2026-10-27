// Whether a successful nightly publication of `sha` resolves an open
// "<channel>-failure" incident. Push runs build in parallel (nightly.yml), so a
// publication of an older commit can finish after a newer commit's failure was
// reported: closing then would lose that newer incident. The incident names
// each failed commit ("... failed on <sha> ..." in its body and comments); it is
// covered only when every one of them is `sha` or one of its ancestors. Anything
// that cannot be established (an unreadable comment list, a failed compare)
// leaves the incident open.

const FAILED_ON = /\b(?:failed on|stale for)\s+([0-9a-f]{40})\b/gi;

export function failedShas(texts) {
  const shas = new Set();
  for (const text of texts) {
    for (const match of String(text || '').matchAll(FAILED_ON)) shas.add(match[1].toLowerCase());
  }
  return [...shas];
}

export async function covers({ github, owner, repo, issue, sha, core }) {
  let comments;
  try {
    comments = await github.paginate(github.rest.issues.listComments, { owner, repo, issue_number: issue.number, per_page: 100 });
  } catch (error) {
    core?.warning?.(`Leaving incident #${issue.number} open: its comments could not be read (${error.status || error.message}).`);
    return false;
  }
  const failed = failedShas([issue.body, ...comments.map((comment) => comment.body)]);
  for (const failure of failed) {
    if (failure === sha.toLowerCase()) continue;
    let status;
    try {
      status = (await github.rest.repos.compareCommitsWithBasehead({ owner, repo, basehead: `${failure}...${sha}` })).data.status;
    } catch (error) {
      core?.warning?.(`Leaving incident #${issue.number} open: ${failure} cannot be compared with ${sha} (${error.status || error.message}).`);
      return false;
    }
    if (status !== 'ahead' && status !== 'identical') {
      core?.notice?.(`Leaving incident #${issue.number} open: it reports ${failure}, which ${sha} does not contain.`);
      return false;
    }
  }
  return true;
}
