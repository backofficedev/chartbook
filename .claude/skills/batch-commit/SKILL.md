---
name: batch-commit
description: Group all outstanding git changes into logical commits and execute them in sequence after user approval.
disable-model-invocation: true
allowed-tools: Bash, Read, Grep, Glob
---

# Batch Commit

Group all outstanding git changes (staged, unstaged, and untracked) into logical commits and execute them in sequence after user approval.

## Phase 1: Gather All Outstanding Changes

Run these commands to get the full picture of uncommitted work:

1. `git status` to see modified, deleted, staged, and untracked files.
2. `git diff` to see unstaged changes in tracked files.
3. `git diff --cached` to see already-staged changes.
4. For each untracked file, read its contents to understand what it does.

Collect the complete list of every file that has any kind of change (modified, deleted, added, or untracked).

## Phase 2: Understand the Changes

For each changed file, understand the nature of the change:

- For modified files: read the diff output to understand what was changed and why.
- For deleted files: note what was removed.
- For new/untracked files: read the file contents to understand its purpose.
- For already-staged files: read the cached diff.

Use Grep and Read as needed to understand how files relate to each other (e.g., a new source file and its corresponding config entry).

## Phase 3: Group Changes into Logical Commits

Cluster the changes into logical groups. Each group becomes one commit. Use these heuristics:

- **Feature coherence**: A new source file + its config registration + its documentation = one commit.
- **Task coherence**: All changes serving the same purpose (e.g., "remove obsolete repo rate charts") belong together.
- **Refactoring**: Code restructuring that does not change behavior groups separately from feature work.
- **Cleanup/deletion**: Removal of obsolete files that share a common theme groups together.
- **Independent modifications**: Changes to unrelated files that serve different purposes go in separate commits.

Order the commits so that foundational changes come first (e.g., new utility code before the notebook that uses it).

Every changed file MUST appear in exactly one commit. Do not leave any file uncommitted. Do not include the same file in multiple commits.

## Phase 4: Present the Plan

Display the proposed commits in this exact format:

```
Proposed commits:

1. <short commit title>
   - path/to/file1
   - path/to/file2

2. <short commit title>
   - path/to/file3
   - path/to/file4
   - path/to/file5

3. <short commit title>
   - path/to/file6
```

Rules for commit titles:
- Title only. No commit body.
- No "Co-Authored-By" line.
- Keep titles under 72 characters.
- Use imperative mood (e.g., "Add", "Remove", "Update", "Refactor").
- Be specific about what changed (e.g., "Add newswire-RavenPack crosswalk script" not "Add new file").

After displaying the plan, ask the user: **"Proceed with these commits? (yes/no)"**

## Phase 5: Wait for Approval

- If the user says **yes** (or equivalent affirmative): proceed to Phase 6.
- If the user says **no** or requests changes: stop and discuss. Do not execute any commits. Let the user describe what they want changed, then regenerate the plan from Phase 3.
- Do NOT proceed without explicit approval.

## Phase 6: Execute Commits

For each proposed commit, in order:

1. Stage only the specific files for that commit:
   ```
   git add path/to/file1 path/to/file2
   ```
   For deleted files, use `git add` (it stages the deletion).
   NEVER use `git add -A`, `git add .`, or `git add --all`.

2. Create the commit with a title-only message:
   ```
   git commit -m "Short commit title here"
   ```
   Do NOT use a multi-line message. Do NOT add a commit body. Do NOT add a Co-Authored-By line.

3. After each commit, briefly confirm it succeeded before moving to the next one.

After all commits are complete, run `git log --oneline -n <number_of_commits>` to show the user a summary of what was committed.

## Important Rules

- NEVER use `git add -A` or `git add .` -- always add specific files by path.
- NEVER commit without user approval.
- NEVER add a Co-Authored-By line to commit messages.
- NEVER add a commit body -- title only.
- Every changed file must appear in exactly one commit group. Verify none are missed.
- If `git commit` fails, diagnose the issue and report it to the user rather than silently continuing.
