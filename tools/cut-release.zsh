#!/usr/bin/env zsh
# cut-release — tag & push a new release, triggering the Release workflow.
#
# Usage:
#   Source this file (e.g. from ~/.zshrc) so `cut-release` is on your PATH,
#   or run it ad-hoc:  source /path/to/tools/cut-release.zsh && cut-release
#
# What it does:
#   1. Refuses if the working tree is dirty.
#   2. Finds the latest vMAJOR.MINOR.PATCH tag.
#   3. Shows the commits since that tag.
#   4. Asks patch/minor/major.
#   5. Computes the new version.
#   6. Confirms with you, then creates an annotated tag and pushes it.
#
# Rolls back the local tag if `git push` fails, so you can retry.

cut-release() {
  emulate -L zsh
  setopt local_options err_return no_unset pipefail

  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    print -u2 "cut-release: not inside a git repository"
    return 1
  fi

  # If the working tree is dirty, offer to commit everything as one commit
  # before proceeding. An empty commit message aborts.
  if ! git diff --quiet || ! git diff --cached --quiet; then
    print "Uncommitted changes:"
    git --no-pager status --short
    print ""
    print -n "Commit message (empty to abort): "
    local commit_msg
    read commit_msg
    if [[ -z "$commit_msg" ]]; then
      print -u2 "cut-release: aborted — nothing committed"
      return 1
    fi
    git add -A
    git commit -m "$commit_msg"
    print ""
  fi

  local branch
  branch=$(git rev-parse --abbrev-ref HEAD)
  if [[ "$branch" != "main" && "$branch" != "master" ]]; then
    print -u2 "cut-release: current branch is '$branch', expected main/master."
    print -n "Continue anyway? (y/N) "
    local go
    read go
    [[ "$go" == "y" || "$go" == "Y" ]] || return 1
  fi

  # If the branch has commits ahead of its upstream, note them — they'll be
  # pushed along with the release tag on the final `git push`.
  if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    local unpushed
    unpushed=$(git rev-list --count '@{u}..HEAD' 2>/dev/null)
    if [[ -n "$unpushed" && "$unpushed" -gt 0 ]]; then
      print "Unpushed commits on $branch ($unpushed) — will push with the release tag:"
      git --no-pager log '@{u}..HEAD' --oneline
      print ""
    fi
  fi

  local latest major minor patch first=0
  latest=$(git tag --list 'v*.*.*' --sort=-v:refname | head -n1)
  if [[ -z "$latest" ]]; then
    print "cut-release: no prior v*.*.* tag. First release will be v0.1.0."
    major=0 minor=1 patch=0 first=1
  else
    print "Latest tag: $latest"
    if [[ "$latest" =~ '^v([0-9]+)\.([0-9]+)\.([0-9]+)$' ]]; then
      major=${match[1]} minor=${match[2]} patch=${match[3]}
    else
      print -u2 "cut-release: tag $latest doesn't match vMAJOR.MINOR.PATCH"
      return 1
    fi

    print ""
    print "Commits since $latest:"
    git --no-pager log --oneline "$latest"..HEAD | head -n 30
    print ""
  fi

  if (( ! first )); then
    local bump
    print -n "Bump (patch / minor / major): "
    read bump
    case "$bump" in
      patch|p) patch=$(( patch + 1 )) ;;
      minor|m) minor=$(( minor + 1 )); patch=0 ;;
      major|M) major=$(( major + 1 )); minor=0; patch=0 ;;
      *) print -u2 "cut-release: invalid bump type '$bump'"; return 1 ;;
    esac
  fi

  local new_version="v${major}.${minor}.${patch}"

  if git rev-parse "$new_version" >/dev/null 2>&1; then
    print -u2 "cut-release: tag $new_version already exists"
    return 1
  fi

  print ""
  print "Will bump manifest, commit, tag and push: $new_version"
  print -n "Proceed? (y/N) "
  local ok
  read ok
  [[ "$ok" == "y" || "$ok" == "Y" ]] || { print "Aborted."; return 1 }

  # Bump the integration's manifest.json version if it exists, and
  # roll that into the release commit so the tagged tree has a
  # consistent version. (HACS surfaces the tag name; HA itself reads
  # the file.)
  local repo_root manifest_path
  repo_root=$(git rev-parse --show-toplevel)
  manifest_path="$repo_root/custom_components/thread_panel/manifest.json"
  if [[ -f "$manifest_path" ]]; then
    python3 - "$manifest_path" "${major}.${minor}.${patch}" <<'PY'
import json, sys, pathlib
path, version = sys.argv[1], sys.argv[2]
p = pathlib.Path(path)
data = json.loads(p.read_text())
data["version"] = version
p.write_text(json.dumps(data, indent=2) + "\n")
PY
    git -C "$repo_root" add "$manifest_path"
    if git -C "$repo_root" diff --cached --quiet; then
      print "cut-release: manifest already at $new_version — no version commit needed"
    else
      git -C "$repo_root" commit -m "Release $new_version"
    fi
  fi

  git tag -a "$new_version" -m "Release $new_version"

  if ! git push origin HEAD "$new_version"; then
    print -u2 "cut-release: push failed — rolling back local tag"
    git tag -d "$new_version" >/dev/null
    return 1
  fi

  local origin repo_path
  origin=$(git remote get-url origin 2>/dev/null || print "")
  if [[ "$origin" =~ 'github\.com[:/]([^/]+/[^/.]+)' ]]; then
    repo_path=${match[1]}
    print ""
    print "Release workflow: https://github.com/$repo_path/actions"
    print "Expected release: https://github.com/$repo_path/releases/tag/$new_version"
  else
    print ""
    print "Tag pushed. (Couldn't parse GitHub URL from origin.)"
  fi
}

# Allow running as a script too: `zsh tools/cut-release.zsh`
if [[ "${ZSH_EVAL_CONTEXT:-}" == *:file ]]; then
  : # sourced — expose the function
else
  cut-release "$@"
fi
