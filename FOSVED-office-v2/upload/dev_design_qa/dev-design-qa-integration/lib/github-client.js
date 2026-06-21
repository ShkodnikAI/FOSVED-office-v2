// ============================================================================
// lib/github-client.js — GitHub API wrapper for Dev Department
// ============================================================================
//
// Wraps Octokit with retry logic, error handling, and Fosved-specific
// operations: create repo with standard scaffold, commit files, create
// snapshot zips, manage branches.
//
// Requires GITHUB_TOKEN in env with `repo` and `workflow` scopes.
// Default org: ShkodnikAI
//
// Used by: lib/dev.js
// ============================================================================

import { Octokit } from '@octokit/rest';

const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
const DEFAULT_ORG = process.env.GITHUB_ORG || 'ShkodnikAI';

let octokitInstance = null;

function getOctokit() {
  if (!GITHUB_TOKEN) {
    throw new Error('GITHUB_TOKEN not set — cannot use GitHub operations');
  }
  if (!octokitInstance) {
    octokitInstance = new Octokit({ auth: GITHUB_TOKEN });
  }
  return octokitInstance;
}

// ─── Retry wrapper ───────────────────────────────────────────────────────────

async function withRetry(operation, maxRetries = 3, label = 'github op') {
  let lastError;
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      // Retryable: rate limit, server errors, network
      const retryable =
        error.status === 429 ||
        error.status === 502 ||
        error.status === 503 ||
        error.code === 'ECONNRESET' ||
        error.code === 'ETIMEDOUT';

      if (!retryable || attempt === maxRetries) {
        console.error(`[github] ${label} failed (attempt ${attempt}):`, error.message);
        throw error;
      }

      // Exponential backoff; respect rate-limit reset if present
      let delay = Math.min(1000 * Math.pow(2, attempt), 30000);
      if (error.status === 429 && error.response?.headers?.['x-ratelimit-reset']) {
        const resetMs = parseInt(error.response.headers['x-ratelimit-reset']) * 1000 - Date.now();
        delay = Math.max(delay, Math.min(resetMs, 60000));
      }
      console.warn(`[github] ${label} retry ${attempt}/${maxRetries} after ${delay}ms`);
      await new Promise(r => setTimeout(r, delay));
    }
  }
  throw lastError;
}

// ─── Repository operations ───────────────────────────────────────────────────

/**
 * Create a new GitHub repository.
 * Returns { fullName, url, defaultBranch }.
 */
export async function createRepository({ name, description, isPrivate = true, org = DEFAULT_ORG }) {
  const octokit = getOctokit();

  const result = await withRetry(async () => {
    // Try org repo creation; fall back to user repo
    try {
      return await octokit.repos.createInOrg({
        org,
        name,
        description: description || '',
        private: isPrivate,
        auto_init: false  // we'll scaffold ourselves
      });
    } catch (e) {
      if (e.status === 404) {
        // org not found or no access — create as user repo
        return await octokit.repos.createForAuthenticatedUser({
          name,
          description: description || '',
          private: isPrivate,
          auto_init: false
        });
      }
      throw e;
    }
  }, 3, `createRepository ${name}`);

  return {
    fullName: result.data.full_name,
    url: result.data.html_url,
    defaultBranch: result.data.default_branch || 'main',
    cloneUrl: result.data.clone_url
  };
}

/**
 * Get repository info + statistics.
 */
export async function getRepository(fullName) {
  const octokit = getOctokit();
  const [owner, repo] = fullName.split('/');

  return withRetry(async () => {
    const { data } = await octokit.repos.get({ owner, repo });
    let commitCount = 0;
    try {
      const commits = await octokit.repos.listCommits({ owner, repo, per_page: 1 });
      // GitHub returns link header for pagination — parse last page for count
      const link = commits.headers.link;
      if (link) {
        const match = link.match(/page=(\d+)>; rel="last"/);
        commitCount = match ? parseInt(match[1]) : 1;
      } else {
        commitCount = commits.data.length;
      }
    } catch (e) { /* empty repo */ }

    return {
      fullName: data.full_name,
      url: data.html_url,
      description: data.description,
      defaultBranch: data.default_branch,
      isPrivate: data.private,
      starsCount: data.stargazers_count,
      commitsCount: commitCount,
      lastCommitAt: data.pushed_at ? new Date(data.pushed_at) : null,
      language: data.language
    };
  }, 3, `getRepository ${fullName}`);
}

/**
 * List repositories in the org/user account.
 */
export async function listRepositories(org = DEFAULT_ORG) {
  const octokit = getOctokit();

  return withRetry(async () => {
    let repos;
    try {
      const { data } = await octokit.repos.listForOrg({ org, per_page: 100 });
      repos = data;
    } catch (e) {
      const { data } = await octokit.repos.listForAuthenticatedUser({ per_page: 100 });
      repos = data;
    }
    return repos.map(r => ({
      fullName: r.full_name,
      url: r.html_url,
      description: r.description,
      isPrivate: r.private,
      language: r.language,
      lastCommitAt: r.pushed_at ? new Date(r.pushed_at) : null
    }));
  }, 3, 'listRepositories');
}

// ─── File operations ─────────────────────────────────────────────────────────

/**
 * Create or update a file in the repo.
 */
export async function putFile({ fullName, path, content, message, branch = 'main' }) {
  const octokit = getOctokit();
  const [owner, repo] = fullName.split('/');

  return withRetry(async () => {
    // Check if file exists (to get sha for update)
    let sha;
    try {
      const { data } = await octokit.repos.getContent({ owner, repo, path, ref: branch });
      sha = data.sha;
    } catch (e) {
      // File doesn't exist — creating new
    }

    const { data } = await octokit.repos.createOrUpdateFileContents({
      owner,
      repo,
      path,
      message,
      content: Buffer.from(content, 'utf-8').toString('base64'),
      branch,
      ...(sha ? { sha } : {})
    });

    return { sha: data.content.sha, commitSha: data.commit.sha };
  }, 3, `putFile ${path}`);
}

/**
 * Put multiple files in a single commit (via Git Data API).
 */
export async function putFiles({ fullName, files, message, branch = 'main' }) {
  const octokit = getOctokit();
  const [owner, repo] = fullName.split('/');

  return withRetry(async () => {
    // Get current branch ref
    let baseSha;
    try {
      const { data: ref } = await octokit.git.getRef({ owner, repo, ref: `heads/${branch}` });
      baseSha = ref.object.sha;
    } catch (e) {
      // Branch doesn't exist — repo may be empty. Different handling needed.
      throw new Error(`Branch ${branch} not found. For empty repos, use putFile to seed first.`);
    }

    const { data: baseCommit } = await octokit.git.getCommit({ owner, repo, commit_sha: baseSha });

    // Create blobs for each file
    const tree = [];
    for (const file of files) {
      const { data: blob } = await octokit.git.createBlob({
        owner, repo,
        content: Buffer.from(file.content, 'utf-8').toString('base64'),
        encoding: 'base64'
      });
      tree.push({ path: file.path, mode: '100644', type: 'blob', sha: blob.sha });
    }

    // Create tree
    const { data: newTree } = await octokit.git.createTree({
      owner, repo,
      base_tree: baseCommit.tree.sha,
      tree
    });

    // Create commit
    const { data: newCommit } = await octokit.git.createCommit({
      owner, repo,
      message,
      tree: newTree.sha,
      parents: [baseSha]
    });

    // Update ref
    await octokit.git.updateRef({ owner, repo, ref: `heads/${branch}`, sha: newCommit.sha });

    return { commitSha: newCommit.sha };
  }, 3, `putFiles (${files.length} files)`);
}

/**
 * Seed an empty repository with initial files (uses Contents API, one file at a time).
 * For brand-new empty repos where Git Data API needs an initial commit first.
 */
export async function seedRepository({ fullName, files, branch = 'main' }) {
  // First file creates the initial commit
  const [first, ...rest] = files;
  await putFile({
    fullName,
    path: first.path,
    content: first.content,
    message: 'Initial commit',
    branch
  });

  // Remaining files in one batched commit
  if (rest.length > 0) {
    await putFiles({
      fullName,
      files: rest,
      message: 'chore: scaffold project structure',
      branch
    });
  }

  return { seeded: files.length };
}

/**
 * Get all files in repo as a flat list (for snapshot).
 */
export async function getRepositoryTree(fullName, branch = 'main') {
  const octokit = getOctokit();
  const [owner, repo] = fullName.split('/');

  return withRetry(async () => {
    const { data: ref } = await octokit.git.getRef({ owner, repo, ref: `heads/${branch}` });
    const { data: tree } = await octokit.git.getTree({
      owner, repo,
      tree_sha: ref.object.sha,
      recursive: 'true'
    });
    return tree.tree.filter(item => item.type === 'blob');
  }, 3, `getRepositoryTree ${fullName}`);
}

/**
 * Download a file's content.
 */
export async function getFileContent(fullName, path, branch = 'main') {
  const octokit = getOctokit();
  const [owner, repo] = fullName.split('/');

  return withRetry(async () => {
    const { data } = await octokit.repos.getContent({ owner, repo, path, ref: branch });
    if (data.content) {
      return Buffer.from(data.content, 'base64').toString('utf-8');
    }
    return null;
  }, 3, `getFileContent ${path}`);
}

// ─── Branch operations ───────────────────────────────────────────────────────

export async function createBranch({ fullName, branchName, fromBranch = 'main' }) {
  const octokit = getOctokit();
  const [owner, repo] = fullName.split('/');

  return withRetry(async () => {
    const { data: ref } = await octokit.git.getRef({ owner, repo, ref: `heads/${fromBranch}` });
    await octokit.git.createRef({
      owner, repo,
      ref: `refs/heads/${branchName}`,
      sha: ref.object.sha
    });
    return { branchName };
  }, 3, `createBranch ${branchName}`);
}

// ─── Pull request operations ─────────────────────────────────────────────────

export async function createPullRequest({ fullName, title, body, head, base = 'main' }) {
  const octokit = getOctokit();
  const [owner, repo] = fullName.split('/');

  return withRetry(async () => {
    const { data } = await octokit.pulls.create({ owner, repo, title, body, head, base });
    return { number: data.number, url: data.html_url };
  }, 3, `createPullRequest ${title}`);
}

// ─── Branch protection ───────────────────────────────────────────────────────

export async function protectMainBranch(fullName) {
  const octokit = getOctokit();
  const [owner, repo] = fullName.split('/');

  try {
    await withRetry(async () => {
      await octokit.repos.updateBranchProtection({
        owner, repo, branch: 'main',
        required_status_checks: { strict: true, contexts: [] },
        enforce_admins: false,
        required_pull_request_reviews: { required_approving_review_count: 0 },
        restrictions: null
      });
    }, 2, 'protectMainBranch');
  } catch (e) {
    // Branch protection requires repo to have commits + may need higher plan
    console.warn('[github] Could not set branch protection:', e.message);
  }
}

// ─── CI status ───────────────────────────────────────────────────────────────

export async function getLatestWorkflowRun(fullName, branch = 'main') {
  const octokit = getOctokit();
  const [owner, repo] = fullName.split('/');

  try {
    return await withRetry(async () => {
      const { data } = await octokit.actions.listWorkflowRunsForRepo({
        owner, repo, branch, per_page: 1
      });
      if (data.workflow_runs.length === 0) return null;
      const run = data.workflow_runs[0];
      return {
        status: run.status,           // queued | in_progress | completed
        conclusion: run.conclusion,   // success | failure | cancelled | null
        url: run.html_url,
        createdAt: new Date(run.created_at)
      };
    }, 2, 'getLatestWorkflowRun');
  } catch (e) {
    return null;
  }
}

// ─── Export ──────────────────────────────────────────────────────────────────

export default {
  createRepository,
  getRepository,
  listRepositories,
  putFile,
  putFiles,
  seedRepository,
  getRepositoryTree,
  getFileContent,
  createBranch,
  createPullRequest,
  protectMainBranch,
  getLatestWorkflowRun
};
