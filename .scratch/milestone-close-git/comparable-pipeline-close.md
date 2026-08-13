# How comparable agent pipelines close onto a protected default

**Ticket:** [How do comparable agent pipelines close onto a protected default?](https://github.com/open-gsd/gsd-path/issues/27)  
**Retrieved:** 2026-08-13  
**Sources:** official product docs and first-party specs only. No blogs, changelogs-as-product-spec, or third-party write-ups.

**Standing veto (not a recommendation space):** the GSD Path pipeline never pushes, merges, or force-updates the default branch.

## Question

From official product docs: how do comparable agent coding pipelines land work onto a protected default branch without the agent pushing or merging that branch? What is the human or CI step?

## Answer

Comparable products finish by pushing a **non-default branch** and opening a **pull request** (or merge request). The protected default is updated only by a **human with write access**, or by **GitHub itself** after that human enables auto-merge or enqueues the PR. GitHub's merge queue is the documented CI lander: a write-access user adds the PR; GitHub builds a temporary merge group and merges into the protected branch.

No official agent-pipeline doc reviewed here describes the coding agent as the actor that should push, merge, or force-update a protected default. Copilot's cloud agent is explicitly forbidden from pushing default. Devin's first-session playbook forbids pushing main. Claude routines reject pushes to GitHub-protected branches. Where a product can merge at all, the merge is a **human-initiated** GitHub action (merge button, auto-merge toggle, or merge-queue enqueue), not the agent's finish step.

## 1. GitHub landing surface

This is the host contract every GitHub-hosted agent inherits. Agents do not replace it.

### Protected default

A branch protection rule can require reviews, status checks, conversation resolution, signed commits, linear history, a merge queue, or successful deployments before anyone can update the matching branch, including by merging a PR ([About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)).

By default each rule **disables force pushes** and **prevents deletion** of matching branches ([About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)).

If required reviews are enabled, **collaborators can only push changes to the protected branch via a pull request** that has the required approving reviews ([About protected branches — Require pull request reviews before merging](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-pull-request-reviews-before-merging)). A failed merge attempt is rejected with `GH006: Protected branch update failed` ([same section](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-pull-request-reviews-before-merging)).

Rulesets can require that all changes to the target branch be associated with a pull request ([Available rules for rulesets — Require a pull request before merging](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-a-pull-request-before-merging)).

### Human merge

When requirements are met, a person merges on GitHub with merge commit, squash, or rebase, then optionally deletes the head branch ([Merging a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/merging-a-pull-request)). Draft PRs cannot be merged ([same page](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/merging-a-pull-request)). The GitHub CLI equivalent is `gh pr merge` ([same page](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/merging-a-pull-request)).

### Auto-merge (human enables; GitHub merges)

People with **write permissions** enable auto-merge on a PR that cannot merge immediately (typically because required reviews or status checks are still outstanding). GitHub then merges automatically after those requirements pass ([Automatically merging a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request)). Auto-merge is disabled if someone without write permissions pushes new changes to the head branch or switches the base ([same page](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request)).

The actor who lands default is GitHub, after a write-access human opts in. The coding agent is not that actor.

### Merge queue (human enqueues; GitHub merges)

Administrators require a merge queue on the base branch via the **Require merge queue** protection setting ([Managing a merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)).

Once required checks pass, **a user with write access adds the PR to the queue** ([About protected branches — Require merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-merge-queue); [Merging a pull request with a merge queue](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/merging-a-pull-request-with-a-merge-queue)). The UI action is **Merge when ready** / **Confirm merge when ready**. `gh pr merge` against a queue-required base adds the PR to the queue if checks have passed, or enables auto-merge if they have not ([same page](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/merging-a-pull-request-with-a-merge-queue)).

GitHub then:

1. Creates temporary branches with a special prefix (`gh-readonly-queue/{base_branch}` for third-party CI) grouping the PR with the latest target and earlier queue entries.
2. Dispatches `merge_group` checks (GitHub Actions must listen for `merge_group`; otherwise required checks never report and the merge fails).
3. Merges into the protected base with the configured merge method once those checks pass.

([Managing a merge queue — How merge queues work](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue#how-merge-queues-work))

Failed CI, timeout, user removal, or an unresolvable protection failure **removes the PR from the queue**; it does not land ([same page](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue#failing-ci)).

The default-branch update is performed by GitHub, not by the PR author pushing default.

## 2. GitHub Copilot coding agent

**Official close path:** new `copilot/` branch → optional or automatic PR → human review → human merge (or human-enabled agent-merge / auto-merge). **Cannot push default.**

Copilot cloud agent "can create branches, write code, and open pull requests" ([Application card: GitHub Copilot Agents](https://docs.github.com/en/copilot/responsible-use/agents)). It "can only push to a single branch: the existing pull request branch when triggered via `@copilot`, or otherwise to a new `copilot/` branch. This means that Copilot cannot push directly to your default branch (for example, `main`)" ([same page — Constrained permissions](https://docs.github.com/en/copilot/responsible-use/agents)).

The intended human workflow is research / plan / code **on a branch before opening a PR**; the developer "chooses to create a pull request when ready" ([About GitHub Copilot cloud agent](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent)). Some entry points open a PR immediately; others leave it to the prompt or session logs ([Using Copilot cloud agent on GitHub](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-on-github); [Starting GitHub Copilot sessions](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/start-copilot-sessions)).

Assigning an issue to Copilot: Copilot "will start working on the task, raise a pull request, then request a review from you when it's finished" ([Using Copilot cloud agent on GitHub — Assigning an issue to Copilot](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-on-github)). Follow-up `@copilot` comments push to the **PR branch**, not default ([same page](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-on-github)).

**Human / CI step after the agent stops:**

- Review the PR. Actions workflows triggered by agent PRs "require approval from a user with write access before they will run" ([Application card — Privilege escalation controls](https://docs.github.com/en/copilot/responsible-use/agents)). The PR merge box has **Approve and run workflows** ([Using Copilot cloud agent on GitHub — Managing GitHub Actions workflow runs](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-on-github)).
- Merge yourself, or enable GitHub auto-merge / a merge queue as in section 1.
- In the Copilot app, a human can enable **agent merge**, which "will prompt the workspace's Copilot session to read your pull request, fix what is blocking it, and merge it as soon as GitHub allows." It turns itself off once the PR is merged ([Managing issues and pull requests with the GitHub Copilot app](https://docs.github.com/en/copilot/how-tos/github-copilot-app/managing-issues-and-pull-requests)). That is a human-armed GitHub merge after GitHub's own requirements pass, not a push to default by the coding session.

Docs that were checked and do **not** describe the cloud agent merging the protected default: [About GitHub Copilot cloud agent](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent), [Using Copilot cloud agent on GitHub](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-on-github).

## 3. Claude Code

**Official close path:** commit on a working / `claude/` branch → push that branch → open a PR → human reviews and merges. Cloud and Actions products stop at the PR. Routines refuse to push a GitHub-protected branch.

### Local / auto mode

Best-practice finish is "Ask Claude to commit with a descriptive message and create a PR" and, in a `/fix-issue` skill, "Push and create a PR" ([Best practices for Claude Code](https://code.claude.com/docs/en/best-practices)).

Auto mode "allows pushes to any branch of the repository you're working in, including the default branch, and pull request creation by default." Force-push stays blocked. **`permissions.deny` can still block specific branches in every mode, and the remote's own branch protection still applies.** A documented checkpoint is `permissions.ask` on `git push` and `gh pr create` ([Configure auto mode — Common boundaries](https://code.claude.com/docs/en/auto-mode-config#common-boundaries); [Choose a permission mode](https://code.claude.com/docs/en/permission-modes)).

The same classifier **blocks by default**: "Merging a pull request no human has approved, approving Claude's own pull request, or disabling CI checks" ([Choose a permission mode — What the classifier blocks by default](https://code.claude.com/docs/en/permission-modes#what-the-classifier-blocks-by-default)).

Before v2.1.203, "any direct push to the default branch was blocked"; later versions allow a local push attempt, but GitHub protection still rejects it on a protected default ([same page](https://code.claude.com/docs/en/permission-modes)).

This is local-tool permission, not an official "push default to close" workflow.

### Claude Code GitHub Actions

The action "analyze[s] code, implement[s] changes, and push[es] commits." Quick setup "pushes a branch with the workflow files… and opens GitHub in your browser with a pull request ready to create. **Create and merge that pull request**" — the human creates and merges the setup PR ([Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions)).

Best practice: "**review Claude's changes before merging**" ([same page — Protect your credentials](https://code.claude.com/docs/en/github-actions)).

The page documents issue/PR comments, scheduled prompts, and review workflows. It does **not** document the action merging into a protected default.

### Claude Code on the web

Cloud sessions "clone code and push branches." The review UI is: inspect the diff, then create a PR from the web ([Use Claude Code on the web — Review changes](https://code.claude.com/docs/en/claude-code-on-the-web#review-changes)). Auto-fix "watch[es] a pull request and automatically respond[s] to CI failures and review comments" and "pushes a fix if one is clear." It does not merge. Merge conflicts require a human to open the session and ask Claude to rebase, because GitHub does not emit a webhook when the base advances ([same page — Auto-fix pull requests](https://code.claude.com/docs/en/claude-code-on-the-web#auto-fix-pull-requests)).

### Routines (scheduled / GitHub-triggered cloud)

"Claude pushes its work to branches prefixed with `claude/`, which are always accepted. When your prompt directs Claude to push to another branch, Claude Code checks the push first and **rejects it if… the branch is protected on GitHub**" (also rejects if someone else has an open PR from that branch, or the branch has commits authored by someone other than you) ([Automate work with routines — Repositories and branch permissions](https://code.claude.com/docs/en/routines#repositories-and-branch-permissions)).

Each run is a session where the human "can see what Claude did, review changes, and create a pull request" ([same page](https://code.claude.com/docs/en/routines)). Example use cases open "a draft pull request with a proposed fix" or "update PRs against the docs repository for an editor to review" ([same page — Example use cases](https://code.claude.com/docs/en/routines)).

**Human / CI step:** create/review the PR, then merge via GitHub (section 1). Routines will not push a protected default.

## 4. OpenAI Codex

**Official close path:** inspect the cloud diff → human opens a PR (or commits/pushes a worktree branch and opens a PR). GitHub integration is **review**, not land.

Codex cloud: "Inspect the summary and diff, request a follow-up, **or open a pull request when the result is ready**." Setup step 5: "Review the summary and diff. Ask Codex to make follow-up changes, or open a pull request when the work is ready" ([Codex cloud](https://developers.openai.com/codex/cloud) / [learn.chatgpt.com Codex cloud](https://learn.chatgpt.com/docs/cloud)).

Desktop worktrees: after **Create branch here**, "you can commit your changes, push your branch to your remote repository, and open a pull request on GitHub" ([Worktrees](https://developers.openai.com/codex/environments/git-worktrees)).

GitHub third-party docs cover Code Review and Security Review: Codex "reviews the pull request diff… and posts a standard GitHub code review." Custom rules "don’t replace tests, branch protections, or required approvals" ([Review GitHub pull requests with Codex](https://developers.openai.com/codex/third-party/github)). `@codex fix it` starts a cloud chat that "will fix the issue and update the pull request" — the PR branch, not default ([Review GitHub pull requests](https://developers.openai.com/codex/use-cases/github-code-reviews)).

The Codex GitHub Action sample reviews PRs and posts a comment; it does not merge ([Codex GitHub Action](https://developers.openai.com/codex/github-action)).

**Pages checked that do not document agent-merge onto a protected default:** [Codex cloud](https://developers.openai.com/codex/cloud), [Worktrees](https://developers.openai.com/codex/environments/git-worktrees), [Review GitHub pull requests with Codex](https://developers.openai.com/codex/third-party/github), [Codex GitHub Action](https://developers.openai.com/codex/github-action).

**Human / CI step:** open/review the PR, then GitHub merge / auto-merge / merge queue (section 1).

## 5. OpenHands

**Official close path:** agent opens a GitHub PR or GitLab MR. No official close/land-onto-protected-default page.

GitHub Cloud: label an issue `openhands` or mention `@openhands`. OpenHands comments, works, then "**Open a pull request if it determines that the issue has been successfully resolved**" and comments with a link to the PR ([GitHub Integration](https://docs.openhands.dev/openhands/usage/cloud/github-installation)). `@openhands` on a PR is for questions, updates, and explanations — not merge ([same page](https://docs.openhands.dev/openhands/usage/cloud/github-installation)).

GitLab Cloud: the same trigger "**Open[s] a merge request if it determines that the issue has been successfully resolved**" ([GitLab Integration](https://docs.openhands.dev/openhands/usage/cloud/gitlab-installation)). A custom `GITLAB_TOKEN` can restrict the agent; "the high-permission API token is still requested and used for other components of the application (e.g. opening merge requests)" ([same page](https://docs.openhands.dev/openhands/usage/cloud/gitlab-installation)).

Other official pages checked: [Automated Code Review](https://docs.openhands.dev/openhands/usage/use-cases/code-review) and [PR Review — GitHub Workflows](https://docs.openhands.dev/sdk/guides/github-workflows/pr-review) describe posting reviews, not merging. [TODO Management](https://docs.openhands.dev/sdk/guides/github-workflows/todo-management) creates a PR per TODO and picks reviewers.

**No official OpenHands page describes merging a protected default or instructing the agent to do so.** Land is the host's PR/MR merge by a human (or GitHub/GitLab auto-merge after a human enables it).

## 6. Devin (Cognition)

**Official close path:** `devin/…` branch → PR → human review. Playbook forbids pushing main. Branch protection is recommended so required checks pass **before Devin can merge**. Merge buttons in Devin Review are human UI over GitHub, not the coding session's finish step.

Integration purpose: "create pull requests, respond to PR comments, and collaborate directly within your repositories" ([GitHub](https://docs.devin.ai/integrations/gh)). Permissions include write to contents and pull requests so Devin can "work in your repositories as a regular contributor—pushing branches, opening pull requests, and participating in PR discussions" ([same page](https://docs.devin.ai/integrations/gh)).

**Security recommendation, stated twice:** "We recommend enabling branch protection rules on your main branch to ensure all required checks pass before Devin can merge changes" ([same page — setup tip and Security Considerations](https://docs.devin.ai/integrations/gh)). That assumes Devin *may* be able to merge if protection allows; it does not document merge as the finish step, and it treats protection as the gate.

The official "Create a quick PR" playbook **Forbidden Actions** include "**Do NOT push directly to the main branch**" and "NEVER force push on branches!" Procedure: checkout `devin/<timestamp>-<name>`, commit, push, `gh` PR, send the link to the user for review ([Your First Session](https://docs.devin.ai/get-started/first-run)).

Devin Review is a **human** review surface. Workflow actions: "Merge — Merge the PR using the repository's configured merge strategy… The merge button reflects the PR's current mergeability status and required checks." Also close, draft, ready, and "**Auto-merge** — Enable or disable GitHub auto-merge from the merge button dropdown. When enabled, the PR will merge automatically once all required checks pass" ([Devin Review — PR Workflow Actions](https://docs.devin.ai/work-with-devin/devin-review)). Those actions "require a GitHub App connection" and are disabled in read-only mode ([same page](https://docs.devin.ai/work-with-devin/devin-review)).

Stacked PRs "merge through GitHub's atomic stack merge" — still GitHub, triggered from the review UI ([same page](https://docs.devin.ai/work-with-devin/devin-review)).

**Human / CI step:** review in GitHub or Devin Review; click merge or enable GitHub auto-merge; branch protection / required checks still apply.

## 7. Cursor Cloud Agents

**Official close path:** isolated branch (`cursor/…` by default) → push → "merge-ready" PR → human reviews and merges (or toggles GitHub auto-merge).

"Cloud agents clone your repo… and work on a separate branch, then push changes to your repo for handoff" ([Cloud Agents](https://cursor.com/docs/cloud-agent)). "Cloud agents produce merge-ready PRs with artifacts to demo their changes" ([same page](https://cursor.com/docs/cloud-agent)).

The Cloud Agents API: by default Cursor "pushes commits to a new auto-generated branch (`cursor/…`)." `autoCreatePR` "Whether Cursor should open a pull request when the run completes" ([Cloud Agents API](https://cursor.com/docs/cloud-agent/api/endpoints)).

GitHub app permissions include "Read branch protection and required check rules **to determine PR mergeability**" and custom roles "so the correct merge and review options appear" ([GitHub](https://cursor.com/docs/integrations/github)). That is mergeability **display**, not an agent push to default.

Cursor for iOS: the human "review[s] and merge[s] their pull requests." You can "merge with squash, mark ready, update the branch, **toggle auto-merge**, publish, or close" ([Cursor for iOS](https://cursor.com/docs/cloud-agent/mobile)).

**Pages checked that do not document the cloud agent pushing or merging a protected default as its finish step:** [Cloud Agents](https://cursor.com/docs/cloud-agent), [GitHub integration](https://cursor.com/docs/integrations/github). Automations can *trigger on* "Pull request merged"; they do not define land ([Automations](https://cursor.com/docs/cloud-agent/automations)).

**Human / CI step:** review the merge-ready PR; merge or enable auto-merge in Cursor / GitHub; GitHub protections still apply.

## Pattern (what is comparable)

| Product | Agent finish (official) | Who updates protected default | Agent push/merge of default? |
| --- | --- | --- | --- |
| GitHub (host) | n/a — PR + checks | Human merge; or GitHub after human auto-merge / merge-queue enqueue | Force-push off by default; required-review branches only via approved PR |
| Copilot cloud agent | `copilot/` branch + PR; request human review | Human merge, or human-enabled agent-merge/auto-merge once GitHub allows | **Cannot push default** |
| Claude Code (Actions / web / routines) | `claude/` (or working) branch + PR | Human creates/reviews/merges the PR | Routines **reject protected-branch pushes**; auto mode still subject to remote protection; merge of unapproved PR blocked |
| Codex cloud / desktop | Diff ready; human opens PR (or push worktree branch + PR) | Human / GitHub auto-merge / queue | **No official land-onto-default docs** |
| OpenHands Cloud | Opens GitHub PR or GitLab MR | Human (host merge / auto-merge) | **No official land-onto-default docs** |
| Devin | `devin/…` branch + PR; playbook forbids pushing main | Human merge or human-enabled GitHub auto-merge in Devin Review | Playbook: **do not push main**; protection recommended before any merge |
| Cursor Cloud Agents | `cursor/…` branch + merge-ready PR | Human merge or auto-merge toggle (web/iOS) | Finish is handoff via PR, not default |

Shared close sequence in official docs:

1. Agent writes on a **non-default** branch (often a product-prefixed name).
2. Agent **opens a PR/MR** (or leaves a reviewable branch for the human to open).
3. **Human** reviews. Some products also require a human to approve Actions on the agent PR.
4. **Human** clicks merge, enables auto-merge, or enqueues a merge queue. **GitHub (or GitLab) performs the default-branch update.**

That sequence does not require the coding pipeline to push, merge, or force-update default.

## Fit to the standing veto

The veto ("pipeline never pushes, merges, or force-updates the default branch") is the **same close shape** these products document: agent stops at a reviewable PR; a human or the host's merge machinery lands default.

What these docs do **not** support as an official agent-finish step:

- Agent `git push` to `main` / default
- Agent `git merge` into default
- Agent force-update of default
- Treating merge-queue temp branches as something the agent should push

What they **do** support as the human/CI lander, if default is to receive the milestone at all:

- Human merge of the PR on GitHub
- Human-enabled GitHub auto-merge
- Human enqueue onto a GitHub merge queue (GitHub then merges)

No recommendation is made here about whether GSD Path should land on default. That is out of this ticket's scope. This ticket only records how comparable official docs close when default is protected.

## Sources

### GitHub

- [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [Merging a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/merging-a-pull-request)
- [Automatically merging a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request)
- [Managing a merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
- [Merging a pull request with a merge queue](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/merging-a-pull-request-with-a-merge-queue)
- [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

### Copilot

- [About GitHub Copilot cloud agent](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent)
- [Using Copilot cloud agent on GitHub](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-on-github)
- [Starting GitHub Copilot sessions](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/start-copilot-sessions)
- [Application card: GitHub Copilot Agents](https://docs.github.com/en/copilot/responsible-use/agents)
- [Managing issues and pull requests with the GitHub Copilot app](https://docs.github.com/en/copilot/how-tos/github-copilot-app/managing-issues-and-pull-requests)

### Claude Code

- [Best practices for Claude Code](https://code.claude.com/docs/en/best-practices)
- [Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions)
- [Choose a permission mode](https://code.claude.com/docs/en/permission-modes)
- [Configure auto mode](https://code.claude.com/docs/en/auto-mode-config)
- [Use Claude Code on the web](https://code.claude.com/docs/en/claude-code-on-the-web)
- [Automate work with routines](https://code.claude.com/docs/en/routines)

### Codex

- [Codex cloud](https://developers.openai.com/codex/cloud)
- [Worktrees](https://developers.openai.com/codex/environments/git-worktrees)
- [Review GitHub pull requests with Codex](https://developers.openai.com/codex/third-party/github)
- [Review GitHub pull requests (use case)](https://developers.openai.com/codex/use-cases/github-code-reviews)
- [Codex GitHub Action](https://developers.openai.com/codex/github-action)

### OpenHands

- [GitHub Integration](https://docs.openhands.dev/openhands/usage/cloud/github-installation)
- [GitLab Integration](https://docs.openhands.dev/openhands/usage/cloud/gitlab-installation)
- [Automated Code Review](https://docs.openhands.dev/openhands/usage/use-cases/code-review)
- [PR Review — GitHub Workflows](https://docs.openhands.dev/sdk/guides/github-workflows/pr-review)
- [TODO Management](https://docs.openhands.dev/sdk/guides/github-workflows/todo-management)

### Devin

- [GitHub](https://docs.devin.ai/integrations/gh)
- [Your First Session](https://docs.devin.ai/get-started/first-run)
- [Devin Review](https://docs.devin.ai/work-with-devin/devin-review)

### Cursor

- [Cloud Agents](https://cursor.com/docs/cloud-agent)
- [Cloud Agents API](https://cursor.com/docs/cloud-agent/api/endpoints)
- [GitHub](https://cursor.com/docs/integrations/github)
- [Cursor for iOS](https://cursor.com/docs/cloud-agent/mobile)
- [Automations](https://cursor.com/docs/cloud-agent/automations)
