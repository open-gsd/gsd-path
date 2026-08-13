# What GitHub protections allow close without mutating default?

Ticket: [What GitHub protections allow close without mutating default?](https://github.com/open-gsd/gsd-path/issues/26)
Map: [Wayfinder: Milestone-close git](https://github.com/open-gsd/gsd-path/issues/21)
Sources: official GitHub Docs and first-party REST API docs only. Retrieved 2026-08-13.

## Question

From GitHub's official docs: which branch protections, rulesets, required-PR rules, merge-queue settings, and tag permissions let an agent open a PR, push a non-default branch, or push a tag, without write access to the default branch?

## Veto (not researched as a product path)

The pipeline never pushes, merges, or force-updates the default branch. This note records what GitHub's own model allows. It does not propose giving the pipeline a bypass, merge right, or force-push right on default.

## Bottom line

GitHub has no repository permission that means "write only non-default branches." Repository **Write** / fine-grained **Contents: write** is repository-wide. What keeps an actor off the default branch is a **classic branch protection rule** or a **branch ruleset** targeting default, not a narrower token scope.

An actor with Write (or Contents: write + Pull requests: write) and **no** Administration, **no** ruleset bypass, and **no** classic restriction allow-list entry can:

- create and push non-protected branches
- open a pull request whose base is default
- create a tag object and push a `refs/tags/*` ref (unless a **tag ruleset** restricts creations/updates)

That same Write actor **can still merge** a PR into default once required reviews/checks pass, and **can enqueue** a merge-queue PR. Those are Write actions. They mutate default. The veto forbids the pipeline from using them even when GitHub would allow them.

Admin (or an explicit bypass) is required to manage protections, push default while it is protected, merge without required reviews, or rename/edit the default branch.

---

## 1. What an actor with write-to-non-default can do

There is no GitHub role or fine-grained permission named "write to non-default." The practical meaning of "write-to-non-default" is:

- org role **Write** (or a fine-grained token / GitHub App with **Contents: write**), **and**
- the default branch is protected so that actor cannot update `refs/heads/<default>`.

### Repository Write is repo-wide

Org repository roles, least to most: Read, Triage, Write, Maintain, Admin. Write is "recommended for contributors who actively push to your project."

Write **can**:

- Push to (write) the assigned repository
- Merge a pull request
- Enable/disable auto-merge on a pull request
- Create and edit releases
- Rename a branch **other than** the default branch
- Approve or request changes on required reviews
- Create status checks

Write **cannot**:

- Manage branch protection rules or repository rulesets (Admin only)
- Push to protected branches under the **classic** model (Maintain and Admin can; Write cannot). Docs note this row "Doesn't apply to rulesets as these have a different bypass model"
- Merge pull requests on protected branches **even if there are no approving reviews** (Admin only)
- Edit or rename the repository's default branch (Admin only)

Source: [Repository roles for an organization](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization).

### Pushing a non-default branch

"You can only create a branch in a repository to which you have write access." Deleting the default branch first requires choosing a new default.

Source: [Managing branches within your repository](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-and-deleting-branches-within-your-repository).

REST: `POST /repos/{owner}/{repo}/git/refs` creates a fully-qualified ref such as `refs/heads/featureA`. `PATCH /repos/{owner}/{repo}/git/refs/{ref}` updates it (Git push). `DELETE` of the default branch returns 422.

Source: [REST API endpoints for Git references](https://docs.github.com/en/rest/git/refs).

Those create/update endpoints require repository permission **Contents: write**. `POST /git/refs` and `PATCH /git/refs/{ref}` also appear under **Workflows: write** as an additional permission (needed when the push touches `.github/workflows`).

Source: [Permissions required for fine-grained personal access tokens](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens) — sections "Repository permissions for Contents" and "Repository permissions for Workflows".

A GitHub App that authenticates Git over HTTPS must request the **Contents** repository permission. Editing Actions files under `.github/workflows` also needs **Workflows**.

Source: [Choosing permissions for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app) — "Choosing permissions for Git access".

Unprotected non-default branches are therefore writable with Contents: write alone. Default stays off-limits only if a protection or ruleset blocks updates to that ref.

### Opening a pull request

UI docs: "Anyone with read access to a repository can create a pull request." A later note qualifies public repos: "you must have write access to the head or the source branch or, for organization-owned repositories, you must be a member of the organization that owns the repository." If you lack write, fork first.

Source: [Creating a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request).

REST `POST /repos/{owner}/{repo}/pulls` repeats the public-repo write-to-head (or org-membership) rule. `base` is "the name of the branch you want the changes pulled into" and must already exist on the current repository. Opening a PR does not update `base`.

Source: [REST API endpoints for pull requests](https://docs.github.com/en/rest/pulls/pulls) — "Create a pull request".

Fine-grained / App permission: **Pull requests: write**. That permission is sufficient for `POST /repos/{owner}/{repo}/pulls`. It is **not** the permission that merges.

Source: [Permissions required for fine-grained personal access tokens](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens) — "Repository permissions for Pull requests".

Read and Triage can "Send pull requests from forks" and submit reviews, but cannot approve required reviews, cannot push, and cannot merge.

Source: [Repository roles for an organization](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization).

### Pushing a tag

See §3. Same Contents: write that creates `refs/heads/*` creates `refs/tags/*`, unless a tag ruleset says otherwise.

### What Write still can do to default (veto-relevant)

After required branch-protection checks pass, "a user with write access to the repository can add the pull request to the queue." GitHub then merges into the target branch.

Sources:

- [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) — "Require merge queue"
- [Managing a merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)

REST merge of a PR is `PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge` (and `…/merge-async`). That endpoint is listed under **Contents: write**, not under Pull requests.

Source: [Permissions required for fine-grained personal access tokens](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens) — "Repository permissions for Contents"; [REST API endpoints for pull requests](https://docs.github.com/en/rest/pulls/pulls) — "Merge a pull request".

So: Write + passing required reviews/checks **is** enough for a human or a token to land on default. Protections do not strip Write of merge. They only delay merge until rules pass, unless Admin bypass is enabled.

---

## 2. What requires Admin / write on default

### Admin-only repository actions (role table)

- Manage branch protection rules and repository rulesets
- Merge PRs on protected branches even if there are no approving reviews
- Edit the repository's default branch
- Rename the default branch
- Change repository settings, visibility, collaborators, webhooks, deploy keys

Maintain (not Write) can push to **classic** protected branches. That does not apply to rulesets.

Source: [Repository roles for an organization](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization).

### Classic branch protection — who may update a matching branch

Default: a protection rule disables force pushes and deletions. Restrictions do **not** apply to people with admin permissions, or to custom roles with "bypass branch protections," unless **Do not allow bypassing the above settings** is on.

**Restrict who can push to matching branches** (org repos on Team / Enterprise Cloud; public Free-org repos): only listed users, teams, or apps may push. They still need Write on the repo. Admins can always push or create a matching branch. If PRs are required, listed pushers still must open a PR. If status checks are required, listed pushers still cannot merge when checks fail. Optional **Restrict pushes that create matching branches** applies the same list to branch creation.

Source: [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) — "Restrict who can push to matching branches"; [Managing a branch protection rule](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule).

REST: `restrictions` is required on the protection payload for org repos; `block_creations: true` extends restrictions to new matching branches.

Source: [REST API endpoints for protected branches](https://docs.github.com/en/rest/branches/branch-protection).

**Lock branch** makes the branch read-only; no commits; cannot delete.

**Allow force pushes** is off by default. Enabling it can allow everyone with at least Write, or only named people/teams. Force push does not override other rules (e.g. required linear history).

**Allow deletions** lets anyone with at least Write delete the protected branch, unless it is locked.

Source: [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

### Rulesets — who may update default

**Restrict updates**: only users with **bypass permissions** can push to matching branches or tags.

**Restrict creations**: only bypass actors can create matching branches or tags.

**Restrict deletions**: only bypass actors can delete matching branches or tags (selected by default).

**Block force pushes**: on by default. If force pushes are blocked, org owners / repo admins cannot rename or change the default branch unless they can bypass.

Bypass list may include: repository admins, organization owners, enterprise owners; the Maintain or Write role (or custom roles based on Write); teams; GitHub Apps; Dependabot. Optional **For pull requests only** means the actor cannot push directly but **can bypass protections and merge the PR**.

Sources:

- [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [Creating rulesets for a repository](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository) — "Granting bypass permissions for your branch or tag ruleset"

Managing rulesets via API is **Administration: write** (`POST/PUT/DELETE /repos/{owner}/{repo}/rulesets`, and the classic `/branches/{branch}/protection*` family).

Source: [Permissions required for fine-grained personal access tokens](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens) — "Repository permissions for Administration".

### Token note

"A token has the same capabilities to access resources and perform actions on those resources that the owner of the token has, and is further limited by any scopes or permissions granted to the token. A token cannot grant additional access capabilities to a user."

Source: [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

A GitHub App **user** access token is the intersection of the app's permissions and the user's role. An **installation** access token depends only on the app's permissions.

Source: [Choosing permissions for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app).

---

## 3. Tag create vs tag push

GitHub's Git database treats these as two different objects.

### Create the annotated tag object (not a ref)

`POST /repos/{owner}/{repo}/git/tags` creates an annotated tag **object**. Official note:

> creating a tag object does not create the reference that makes a tag in Git. If you want to create an annotated tag in Git, you have to do this call to create the tag object, and then create the `refs/tags/[tag]` reference. If you want to create a lightweight tag, you only have to create the tag reference — this call would be unnecessary.

The tags API supports annotated tag objects only, not lightweight tags.

Source: [REST API endpoints for Git tags](https://docs.github.com/en/rest/git/tags).

Fine-grained permission: **Contents: write** (`POST /git/tags` has no additional-permission alternative).

Source: [Permissions required for fine-grained personal access tokens](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).

### Push / create the tag ref

`POST /repos/{owner}/{repo}/git/refs` with `ref: refs/tags/<name>` creates the tag pointer. `PATCH` of that ref moves it (the git equivalent of pushing an updated tag). `GET …/git/ref/tags/<name>` reads it.

Source: [REST API endpoints for Git references](https://docs.github.com/en/rest/git/refs).

`git push origin <tag>` is this ref update, authenticated with Contents: write (App: Contents repository permission).

### Releases vs tags

"Releases are based on Git tags, which mark a specific point in your repository's history." Creating a release can choose an existing tag or type a new version number to create a tag.

Sources: [About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases); [Managing releases in a repository](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).

Write can "Create and edit releases." `POST /repos/{owner}/{repo}/releases` is **Contents: write** (also listed under Workflows: write as additional).

Sources: [Repository roles for an organization](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization); [Permissions required for fine-grained personal access tokens](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).

A release that creates a new tag therefore needs Contents: write plus whatever tag ruleset applies.

### Tag rulesets (the current tag-permission model)

Rulesets can target **tags** as well as branches. You create a tag ruleset with **New tag ruleset**. Tag protections use the same restrict-creations / restrict-updates / restrict-deletions / block-force-pushes rules. Example given in the docs: control "who can delete or rename a tag."

Sources:

- [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- [Creating rulesets for a repository](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)
- [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

So:

| Intent | GitHub mechanism | Who, if no tag ruleset |
| --- | --- | --- |
| Create annotated tag object | `POST /git/tags` | Contents: write |
| Create / push tag name (`refs/tags/*`) | `POST /git/refs` or `git push` | Contents: write |
| Move an existing tag | `PATCH /git/refs/tags/…` or force-push tag | Contents: write; blocked if ruleset **Restrict updates** or **Block force pushes** |
| Delete a tag | `DELETE /git/refs/tags/…` | Contents: write; blocked if ruleset **Restrict deletions** |
| Create tag as part of a Release | `POST /releases` | Contents: write + Write role |

A tag ruleset with **Restrict creations** targeting `milestone/**/*` (or similar) means only bypass actors can create those tag names. An agent with Contents: write and **no** tag-ruleset bypass can still create other tags, and can still create the annotated object (the object is not a ref). Official docs do not say that `POST /git/tags` is itself blocked by a tag ruleset; the ruleset language is "create branches or tags whose name matches the pattern" — that is the **ref**.

### Retired classic tag protection

The former docs path `…/configuring-tag-protection-rules` now serves the ruleset creation page. GitHub Enterprise Server 3.17 release notes: "tag protection rules will be migrated to a ruleset, and the tag protection rule feature will no longer be available."

Sources: redirected [configuring-tag-protection-rules](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/configuring-tag-protection-rules) → [Creating rulesets for a repository](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository); [GHES 3.17 release notes](https://docs.github.com/enterprise-server@3.17/admin/release-notes).

---

## 4. Required reviewers, merge queue, rulesets vs classic branch protection

### Both can protect default; they layer

Rulesets and classic branch protection "work alongside each other, and all applicable rules are enforced." Multiple rulesets can apply to the same branch; only one classic rule can. When the same rule is defined more than once, the **most restrictive** version wins. Example: ruleset requires 3 reviews + signed commits; classic requires 2 reviews + linear history → result is 3 reviews + signed commits + linear history.

Anyone with read access can view active rulesets.

Source: [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets) — "About rulesets and protected branches", "About rule layering".

### Classic settings that affect merge into default

From [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches):

| Setting | Effect on a Write actor |
| --- | --- |
| **Require pull request reviews before merging** | Changes reach the protected branch only via a PR approved by the required number of Write reviewers (or code owners). Request-changes from an admin must be approved by that admin, or dismissed by anyone with Write. |
| **Dismiss stale pull request approvals when new commits are pushed** | New diff dismisses approvals. Manual merge-commit + direct push fails unless it matches GitHub's merge. |
| **Require approval of the most recent reviewable push** | Someone other than the last pusher must approve. Same direct-push caveat. |
| **Require status checks before merging** | Checks must be `successful`, `skipped`, or `neutral`. Strict = branch must be up to date. |
| **Require conversation resolution before merging** | All PR comments resolved. |
| **Require signed commits** | Only signed+verified commits may be pushed. |
| **Require linear history** | No merge commits; squash or rebase only. |
| **Require merge queue** | After required checks, Write users enqueue; GitHub merges. |
| **Require deployments to succeed before merging** | Named environments must succeed. |
| **Lock branch** | Read-only. |
| **Do not allow bypassing the above settings** | Admins and "bypass branch protections" custom roles are also bound. |
| **Restrict who can push to matching branches** | Allow-list only (plus admins). |
| **Allow force pushes / Allow deletions** | Off by default. |

Required reviews: "collaborators can only push changes to a protected branch via a pull request that is approved by the required number of reviewers with write permissions."

### Ruleset equivalents

From [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets):

| Ruleset rule | Notes |
| --- | --- |
| **Require a pull request before merging** | "The pull request doesn't necessarily have to be approved, but it must be opened." Optional: N approving reviews, code owners, dismiss stale, last-pusher cannot sole-approve, restrict who dismisses, resolve conversations, required merge type (merge/squash/rebase), required reviewers (up to 15 teams, 0–10 approvals, file patterns). |
| **Require status checks to pass before merging** | Same loose/strict model. Enterprise Cloud adds "Do not require status checks on creation." |
| **Require merge queue** | **Repository-level rulesets only**, not organization-level. Settings: merge method, build concurrency, min/max group size, wait time, require all queue entries to pass, status-check timeout. |
| **Restrict creations / updates / deletions** | Bypass-only. This is how default becomes unwritable to a Write agent without putting the agent on a classic restriction allow-list. |
| **Block force pushes** | Default on. |
| **Require signed commits / linear history / deployments** | Same idea as classic. |
| **Require code scanning / code quality / coverage** | Ruleset-only merge gates. |
| Push-ruleset file path/size/extension | Applies to **every** push, including non-default branches. Not a default-only control. |

Enterprise Cloud also has **Require workflows to pass before merging** (org/enterprise rulesets). Docs warn this "will block direct pushes" and "should only be added to rulesets that target branches where all changes to the branch are performed by pull requests" — do not target all branches.

Source: [Available rules for rulesets (Enterprise Cloud)](https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).

### Merge queue specifics

- Enabled as classic **Require merge queue**, or as a **repository** ruleset rule (not org-level).
- Cannot be enabled with classic branch protection that uses `*` in the branch name pattern.
- Write user enqueues after required checks pass. GitHub creates temporary branches (`gh-readonly-queue/{base_branch}` / `merge_group`) and merges into `base_branch` when checks pass.
- CI must handle `merge_group` (Actions) or those temporary branches (third-party).
- Admins may still **Merge without waiting for requirements to be met (bypass branch protections)** if the protection allows bypass.

Sources:

- [Managing a merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
- [Merging a pull request with a merge queue](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-a-pull-request-with-a-merge-queue)
- [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)

`merge-async` accepts `merge_action`: `default` | `direct_merge` | `merge_queue`.

Source: [REST API endpoints for pull requests](https://docs.github.com/en/rest/pulls/pulls) — "Merge a pull request asynchronously".

Fine-grained PAT / App permission name **Merge queues** (`merge_queues`) exists as `read`/`write`. Official docs list it in the permission table; they do not spell out a distinct "enqueue without Contents: write" path. Enqueue is documented as a Write-access user action.

Source: [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) — repository permissions table.

### Comparison that matters for close-without-mutating-default

| Goal | Classic | Rulesets |
| --- | --- | --- |
| Stop Write from pushing default | **Require pull request reviews** and/or **Restrict who can push** (omit the agent) | **Require a pull request before merging** and/or **Restrict updates** targeting default (do not put the agent on the bypass list) |
| Stop force-update of default | Default (force push off) | **Block force pushes** (default on) |
| Stop Admin from pushing/merging anyway | **Do not allow bypassing the above settings** | Omit Admin from the bypass list (admins are not implicit bypassers the way they are in classic) |
| Required reviewers | Setting on the protection rule | Optional extra on **Require a pull request before merging** |
| Merge queue | **Require merge queue** on the base-branch rule; no `*` patterns | Repository ruleset rule only |
| Protect tags | Not available (retired) | Separate **tag ruleset** |
| Several policies on one branch | Only one classic rule applies | Rules aggregate; most restrictive wins |
| Who can see the policy | Admin settings | Anyone with Read |

**For pull requests only** bypass is **not** compatible with the veto: that actor "can then choose to bypass any branch protections and merge that pull request."

Source: [Creating rulesets for a repository](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository).

---

## 5. Fine-grained PAT / GitHub App permission names

Display names and query-parameter names from [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens):

| Display name | Parameter | Levels | Enough for |
| --- | --- | --- | --- |
| **Contents** | `contents` | read, write | Push branches, create/update/delete refs, create annotated tag objects, merge a PR (`PUT …/pulls/{n}/merge`), create releases, Git-over-HTTPS |
| **Pull requests** | `pull_requests` | read, write | Open / update a PR (`POST/PATCH …/pulls`). Does **not** merge. |
| **Workflows** | `workflows` | write | Required in addition to Contents when the push edits `.github/workflows` |
| **Merge queues** | `merge_queues` | read, write | Named permission; enqueue itself is documented as Write-access, and merge endpoints sit under Contents |
| **Metadata** | `metadata` | read | Implicit/required companion; read-only |
| **Administration** | `administration` | read, write | Manage protections and rulesets. **Not** required to open a PR, push a non-default branch, or push a tag |

GitHub's own token template for "Update code and open a pull request" is `contents=write&pull_requests=write&workflows=write`.

Source: [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) — "Pre-filling fine-grained personal access token details using URL parameters".

### Minimum named permissions for the three close actions (without default write)

These permissions do **not** themselves grant default-branch write. Default-branch write is prevented by protections/rulesets on that ref.

| Action | Fine-grained PAT / GitHub App repository permissions | Must not have |
| --- | --- | --- |
| Push a non-default branch | **Contents: write** (+ **Workflows: write** if workflow files change) | Ruleset bypass on the default-branch ruleset; classic restriction allow-list for default; Administration is unnecessary |
| Open a PR (base = default) | **Pull requests: write**, plus write on the **head** branch (Contents: write, or a fork) | — |
| Create annotated tag object | **Contents: write** (`POST /git/tags`) | — |
| Push tag ref | **Contents: write** (`POST /git/refs` → `refs/tags/…`) | Tag-ruleset bypass if creations/updates are restricted |
| Merge / enqueue onto default | **Contents: write** (and Write role). GitHub allows this after required checks. | **Veto:** the pipeline must not use this even if granted |

Do **not** grant **Administration: write** for close. That permission is what creates and edits protections.

Do **not** put the agent on a ruleset bypass list (including **For pull requests only**). That is how a Write actor becomes able to merge default without reviews.

A PAT cannot exceed the user's role. If the user is Admin, Contents: write on their token can still merge or (if classic bypass is allowed) push default. Bind default with **Do not allow bypassing** (classic) or a ruleset that does not list that actor, and keep Administration off the token.

Sources: [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens); [Choosing permissions for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app); [Permissions required for fine-grained personal access tokens](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens); [Permissions required for GitHub Apps](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps).

Classic PAT scope `repo` is broader (all repos the user can access) and is not a way to avoid default write.

Source: [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) — "Personal access tokens (classic)".

---

## Implications for the veto (facts only)

GitHub will not give the pipeline a "non-default-only" credential. The supported shape is:

1. Actor = Write / Contents: write + Pull requests: write, no Administration.
2. Default branch = classic protection and/or ruleset: require a PR (and, if wanted, required reviews), restrict updates, block force pushes; agent not on the restrict-push allow-list; agent not on the ruleset bypass list; prefer **Do not allow bypassing** if the token owner is an Admin.
3. Tags = Contents: write. Optionally a **tag ruleset** if some names should be bypass-only.
4. Landing onto default, if the map later requires it, is a **human or CI** Write action (merge button, `gh pr merge`, or merge queue). The merge-queue merge is performed by GitHub after a Write user enqueues — that enqueue is still a mutation trigger and is out of bounds for the pipeline under the veto.

This ticket does not decide whether default must contain the milestone. It only records that GitHub can leave default untouched while an agent pushes a branch, opens a PR, and/or pushes a tag.

---

## Sources opened

- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule
- https://docs.github.com/en/rest/branches/branch-protection
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
- https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue
- https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-a-pull-request-with-a-merge-queue
- https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization
- https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request
- https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-and-deleting-branches-within-your-repository
- https://docs.github.com/en/rest/git/refs
- https://docs.github.com/en/rest/git/tags
- https://docs.github.com/en/rest/pulls/pulls
- https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens
- https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps
- https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
- https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app
- https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository
- https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/configuring-tag-protection-rules (redirects to ruleset creation)
- https://docs.github.com/enterprise-server@3.17/admin/release-notes

## Dead ends

- Classic **tag protection rules** on github.com: the documented URL redirects to ruleset creation. Treat tag rulesets as the current control. GHES 3.17 notes the migration/retirement.
- No official permission named "contents:write except default branch." Searched roles, fine-grained PAT permission tables, and App permission docs.
- **Merge queues** (`merge_queues`) is a listed fine-grained permission; official docs do not define it as a way to mutate default without Contents/Write. Enqueue is documented as a Write-access user action.
- Personal-account repositories have only owner vs collaborator (collaborator = write). No Triage/Maintain split. Same protection/ruleset model still applies to the default branch.

Source: [Permission levels for a personal account repository](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/permission-levels-for-a-personal-account-repository).
