#!/usr/bin/env zsh
# cut-release — build artifacts, tag, push, and publish a GitHub release.
#
# Usage:
#   Source this file (e.g. from ~/.zshrc) so `cut-release` is on your PATH,
#   or run it ad-hoc:  source /path/to/tools/cut-release.zsh && cut-release
#
# Prerequisites (checked at start, bails with install instructions if missing):
#   - Active ESP-IDF v6.0 shell ($IDF_PATH set; run `idf` first)
#   - gum (`brew install gum`) — interactive prompts
#   - gh (`brew install gh && gh auth login`) — release creation + upload
#   - yarn — UI build
#   - python3 — manifest writing + sha256
#
# Flow:
#   1. Check prereqs, branch, working tree, unpushed commits.
#   2. Show commits since the last tag, prompt for version bump (gum,
#      npm-style flat menu with prerelease support).
#   3. Bump the integration manifest.json, commit, tag, push.
#   4. Build per-panel UI bundles, per-panel firmware bins, bridge tarball,
#      integration zip into /tmp/panel-release-<version>/.
#   5. Compute sha256 + size, write manifest.json.
#   6. Auto-generate release notes from `git log` since prior tag; offer to
#      edit before publishing.
#   7. `gh release create` with all artifacts; `--prerelease` if version
#      contains a `-` (semver prerelease tag).
#
# Exit early on any failure. Does NOT roll back tag/push if the artifact
# build or release-create step fails — fix the issue and re-run with the
# same version (delete tag manually if needed: `git tag -d` + `git push
# --delete origin <tag>`).

# ===== helpers =====

_cr_check_prereqs() {
  local missing=()
  if [[ -z "${IDF_PATH:-}" || -z "${IDF_PYTHON_ENV_PATH:-}" ]]; then
    missing+=("ESP-IDF v6.0 shell (run \`idf\` first; both \$IDF_PATH and \$IDF_PYTHON_ENV_PATH must be set)")
  fi
  (( $+commands[gum] )) || missing+=("gum (\`brew install gum\`)")
  (( $+commands[gh] )) || missing+=("gh (\`brew install gh && gh auth login\`)")
  (( $+commands[yarn] )) || missing+=("yarn")
  (( $+commands[python3] )) || missing+=("python3")
  if (( ${#missing} )); then
    print -u2 "cut-release: missing prerequisites:"
    local m; for m in $missing; do print -u2 "  - $m"; done
    return 1
  fi
}

# Parse vMAJOR.MINOR.PATCH[-TAG.N] into globals. Returns 0 on success.
_cr_parse_version() {
  local v=$1
  if [[ "$v" =~ '^v([0-9]+)\.([0-9]+)\.([0-9]+)(-([a-z]+)\.([0-9]+))?$' ]]; then
    _cr_major=${match[1]}
    _cr_minor=${match[2]}
    _cr_patch=${match[3]}
    _cr_pre_tag=${match[5]:-}
    _cr_pre_num=${match[6]:-}
    return 0
  fi
  return 1
}

# Strip leading 'v' from a version string. cut-release uses v-prefixed tags
# but artifact filenames + manifest.json use the bare version.
_cr_no_v() { print -- "${1#v}" }

# Interactive bump prompt. Reads current globals (set by _cr_parse_version),
# prints new vX.Y.Z[-tag.N] on stdout.
_cr_prompt_bump() {
  local current=$1
  local is_pre=0
  [[ -n "${_cr_pre_tag:-}" ]] && is_pre=1

  local pp=$((_cr_patch + 1))
  local mp=$((_cr_minor + 1))
  local Mp=$((_cr_major + 1))
  local prev_patch="v${_cr_major}.${_cr_minor}.${pp}"
  local prev_minor="v${_cr_major}.${mp}.0"
  local prev_major="v${Mp}.0.0"

  local choices choice
  if (( is_pre )); then
    local pn=$((_cr_pre_num + 1))
    local prev_pre="v${_cr_major}.${_cr_minor}.${_cr_patch}-${_cr_pre_tag}.${pn}"
    local prev_promote="v${_cr_major}.${_cr_minor}.${_cr_patch}"
    choices=(
      "prerelease    → ${prev_pre}"
      "promote       → ${prev_promote}"
      "patch         → ${prev_patch}"
      "minor         → ${prev_minor}"
      "major         → ${prev_major}"
      "pre-patch     → ${prev_patch}-?.1"
      "pre-minor     → ${prev_minor}-?.1"
      "pre-major     → ${prev_major}-?.1"
      "custom"
    )
  else
    choices=(
      "patch         → ${prev_patch}"
      "minor         → ${prev_minor}"
      "major         → ${prev_major}"
      "pre-patch     → ${prev_patch}-?.1"
      "pre-minor     → ${prev_minor}-?.1"
      "pre-major     → ${prev_major}-?.1"
      "custom"
    )
  fi

  choice=$(gum choose --header "Bump (current: ${current}):" "${choices[@]}") || return 1
  [[ -n "$choice" ]] || return 1

  local new_version
  case "$choice" in
    patch*)        new_version="${prev_patch}" ;;
    minor*)        new_version="${prev_minor}" ;;
    major*)        new_version="${prev_major}" ;;
    prerelease*)
      local pn=$((_cr_pre_num + 1))
      new_version="v${_cr_major}.${_cr_minor}.${_cr_patch}-${_cr_pre_tag}.${pn}"
      ;;
    promote*)      new_version="v${_cr_major}.${_cr_minor}.${_cr_patch}" ;;
    pre-patch*|pre-minor*|pre-major*)
      local base
      case "$choice" in
        pre-patch*) base="${prev_patch}" ;;
        pre-minor*) base="${prev_minor}" ;;
        pre-major*) base="${prev_major}" ;;
      esac
      local pre_tag
      pre_tag=$(gum choose --header "Prerelease tag:" "alpha" "beta" "rc") || return 1
      [[ -n "$pre_tag" ]] || return 1
      new_version="${base}-${pre_tag}.1"
      ;;
    custom*)
      new_version=$(gum input --header "Custom version (e.g. v2.0.0-beta.3):" --placeholder "v2.0.0-beta.3") || return 1
      [[ -n "$new_version" ]] || return 1
      ;;
    *) print -u2 "cut-release: invalid choice"; return 1 ;;
  esac

  if ! [[ "$new_version" =~ '^v[0-9]+\.[0-9]+\.[0-9]+(-[a-z]+\.[0-9]+)?$' ]]; then
    print -u2 "cut-release: '$new_version' doesn't match vMAJOR.MINOR.PATCH[-TAG.N]"
    return 1
  fi

  print -- "$new_version"
}

# Read project_name from a built ESP-IDF firmware's project_description.json.
_cr_firmware_project_name() {
  local firmware_dir=$1
  python3 -c "
import json, sys
print(json.load(open('${firmware_dir}/build/project_description.json'))['project_name'])
" 2>/dev/null
}

# Extract <org>/<repo> from origin remote — used to substitute __REPO__ in
# scripts + Python sources at release build time, so source files stay clean
# of hardcoded values. Handles both git@github.com:org/repo.git and
# https://github.com/org/repo.git forms.
_cr_gh_repo() {
  local repo_root=$1
  local origin
  origin=$(git -C "$repo_root" remote get-url origin 2>/dev/null || print "")
  if [[ "$origin" =~ 'github\.com[:/]([^/]+/[^/.]+)' ]]; then
    print -- "${match[1]}"
  fi
}

# In-place substitute __REPO__ → $2 in $1, preserving the original file
# mode. Without preserving mode, scripts lose their +x bit (the `>`
# redirect creates the temp file with default umask) and systemd's
# ExecStart fails with "Permission denied" / status 203/EXEC.
_cr_substitute_repo() {
  local file="$1" repo="$2"
  python3 - "$file" "$repo" <<'PY'
import os, sys
path, repo = sys.argv[1], sys.argv[2]
mode = os.stat(path).st_mode
data = open(path).read().replace("__REPO__", repo)
open(path, "w").write(data)
os.chmod(path, mode)
PY
}

# Compute size + sha256 of a file. Outputs JSON object {size, sha256}.
_cr_file_meta() {
  local file=$1
  python3 - "$file" <<'PY'
import hashlib, json, os, sys
p = sys.argv[1]
size = os.path.getsize(p)
h = hashlib.sha256()
with open(p, 'rb') as f:
    for chunk in iter(lambda: f.read(65536), b''):
        h.update(chunk)
print(json.dumps({"size": size, "sha256": h.hexdigest()}))
PY
}

# ===== main =====

cut-release() {
  emulate -L zsh
  setopt local_options err_return no_unset pipefail

  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    print -u2 "cut-release: not inside a git repository"
    return 1
  fi

  _cr_check_prereqs || return 1

  local repo_root
  repo_root=$(git rev-parse --show-toplevel)

  # ----- working-tree handling -----
  if ! git -C "$repo_root" diff --quiet || ! git -C "$repo_root" diff --cached --quiet; then
    print "Uncommitted changes:"
    git -C "$repo_root" --no-pager status --short
    print ""
    local commit_msg
    commit_msg=$(gum input --header "Commit message (empty to abort):" --placeholder "Pre-release cleanup") || return 1
    if [[ -z "$commit_msg" ]]; then
      print -u2 "cut-release: aborted — nothing committed"
      return 1
    fi
    git -C "$repo_root" add -A
    git -C "$repo_root" commit -m "$commit_msg"
    print ""
  fi

  # ----- branch check -----
  local branch
  branch=$(git -C "$repo_root" rev-parse --abbrev-ref HEAD)
  if [[ "$branch" != "main" && "$branch" != "master" ]]; then
    print "cut-release: current branch is '$branch', expected main/master."
    gum confirm "Continue anyway?" || return 1
  fi

  # ----- unpushed commits notice -----
  if git -C "$repo_root" rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    local unpushed
    unpushed=$(git -C "$repo_root" rev-list --count '@{u}..HEAD' 2>/dev/null)
    if [[ -n "$unpushed" && "$unpushed" -gt 0 ]]; then
      print "Unpushed commits on $branch ($unpushed) — will push with the release tag:"
      git -C "$repo_root" --no-pager log '@{u}..HEAD' --oneline
      print ""
    fi
  fi

  # ----- version bump -----
  local latest first=0
  latest=$(git -C "$repo_root" tag --list 'v*' --sort=-v:refname | head -n1)
  if [[ -z "$latest" ]]; then
    print "cut-release: no prior v*.*.* tag. First release will be v0.1.0."
    _cr_major=0 _cr_minor=1 _cr_patch=0 _cr_pre_tag="" _cr_pre_num=""
    first=1
  else
    print "Latest tag: $latest"
    if ! _cr_parse_version "$latest"; then
      print -u2 "cut-release: tag $latest doesn't match vMAJOR.MINOR.PATCH[-TAG.N]"
      return 1
    fi
    print ""
    print "Commits since $latest:"
    git -C "$repo_root" --no-pager log --oneline "$latest"..HEAD | head -n 30
    print ""
  fi

  local new_version
  if (( first )); then
    new_version="v0.1.0"
  else
    new_version=$(_cr_prompt_bump "$latest") || return 1
  fi

  if git -C "$repo_root" rev-parse "$new_version" >/dev/null 2>&1; then
    print -u2 "cut-release: tag $new_version already exists"
    return 1
  fi

  # Pre-flight: GitHub release with this tag must not already exist (a leftover
  # from a previous failed run will cause `gh release create` to fail late, after
  # the tag has been pushed). Offer to delete it now if found.
  if ( cd "$repo_root" && gh release view "$new_version" >/dev/null 2>&1 ); then
    print ""
    print -u2 "cut-release: a GitHub release for $new_version already exists (likely leftover from a previous failed run)."
    if gum confirm "Delete the existing release and continue?"; then
      ( cd "$repo_root" && gh release delete "$new_version" --yes ) || {
        print -u2 "cut-release: failed to delete existing release"
        return 1
      }
    else
      return 1
    fi
  fi

  local is_prerelease=0
  [[ "$new_version" == *-* ]] && is_prerelease=1

  print ""
  print "Will tag, push, build artifacts, and publish: $new_version"
  (( is_prerelease )) && print "  (marked as prerelease — \`hacs.json\` Include-prereleases must be on for HACS to surface it)"
  gum confirm "Proceed?" || { print "Aborted."; return 1 }

  # ----- bump integration manifest.json -----
  local manifest_path="$repo_root/platform/integration/thread_panel/manifest.json"
  local version_header="$repo_root/platform/firmware/components/panel_platform/include/panel_version.h"
  local bare_version
  bare_version=$(_cr_no_v "$new_version")
  if [[ -f "$manifest_path" ]]; then
    python3 - "$manifest_path" "$bare_version" <<'PY'
import json, sys, pathlib
path, version = sys.argv[1], sys.argv[2]
p = pathlib.Path(path)
data = json.loads(p.read_text())
data["version"] = version
p.write_text(json.dumps(data, indent=2) + "\n")
PY
    git -C "$repo_root" add "$manifest_path"
  fi
  # Bump the firmware's PANEL_VERSION constant. C6 publishes this retained
  # at state/version on every MQTT connect; HA's update.panel_firmware
  # entity (Phase 3) reads it as installed_version.
  if [[ -f "$version_header" ]]; then
    python3 - "$version_header" "$new_version" <<'PY'
import re, sys, pathlib
path, version = sys.argv[1], sys.argv[2]
p = pathlib.Path(path)
text = p.read_text()
new_text = re.sub(r'^#define PANEL_VERSION ".*"$',
                  f'#define PANEL_VERSION "{version}"',
                  text, count=1, flags=re.MULTILINE)
p.write_text(new_text)
PY
    git -C "$repo_root" add "$version_header"
  fi
  if git -C "$repo_root" diff --cached --quiet; then
    print "cut-release: version files already at $new_version — no version commit needed"
  else
    git -C "$repo_root" commit -m "Release $new_version"
  fi

  # ----- tag + push -----
  git -C "$repo_root" tag -a "$new_version" -m "Release $new_version"
  if ! git -C "$repo_root" push origin HEAD "$new_version"; then
    print -u2 "cut-release: push failed — rolling back local tag"
    git -C "$repo_root" tag -d "$new_version" >/dev/null
    return 1
  fi

  # ----- artifact build phase -----
  local staging="/tmp/panel-release-${new_version}"
  rm -rf "$staging"
  mkdir -p "$staging"

  print ""
  print "Building artifacts in $staging/..."

  # Per-panel UI + firmware
  local panel_dir panel_id ui_dir firmware_dir
  for panel_dir in "$repo_root"/panels/*; do
    [[ -d "$panel_dir" ]] || continue
    panel_id=$(basename "$panel_dir")

    # UI
    ui_dir="$panel_dir/ui"
    if [[ -d "$ui_dir" ]]; then
      print ""
      print "→ ${panel_id} UI..."
      if [[ ! -d "$ui_dir/node_modules" ]]; then
        print -u2 "cut-release: $ui_dir/node_modules missing — run 'yarn install' there first"
        return 1
      fi
      ( cd "$ui_dir" && yarn build ) || return 1
      if [[ ! -d "$ui_dir/dist" ]]; then
        print -u2 "cut-release: $ui_dir/dist missing after build"
        return 1
      fi
      tar -czf "$staging/${panel_id}-ui-${bare_version}.tar.gz" -C "$ui_dir/dist" . || return 1
    fi

    # Firmware
    firmware_dir="$panel_dir/firmware"
    if [[ -d "$firmware_dir" && -f "$firmware_dir/CMakeLists.txt" ]]; then
      print ""
      print "→ ${panel_id} firmware..."
      # idf.py is an alias in interactive shells — aliases don't expand
      # inside function bodies in zsh, so invoke through the explicit
      # python+script path (same approach as the user's `idf` zsh function).
      ( cd "$firmware_dir" && "$IDF_PYTHON_ENV_PATH/bin/python" "$IDF_PATH/tools/idf.py" build ) || return 1
      local project_name bin_path
      project_name=$(_cr_firmware_project_name "$firmware_dir")
      [[ -n "$project_name" ]] || { print -u2 "cut-release: couldn't read project_name from $firmware_dir/build/project_description.json"; return 1 }
      bin_path="$firmware_dir/build/${project_name}.bin"
      [[ -f "$bin_path" ]] || { print -u2 "cut-release: firmware bin not found at $bin_path"; return 1 }
      cp "$bin_path" "$staging/${panel_id}-firmware-${bare_version}.bin" || return 1
    fi
  done

  # Bridge tarball — package source minus build/cache cruft
  print ""
  print "→ panel-bridge..."
  tar -czf "$staging/panel-bridge-${bare_version}.tar.gz" \
    -C "$repo_root/platform/bridge" \
    --exclude='__pycache__' \
    --exclude='*.egg-info' \
    --exclude='.pytest_cache' \
    --exclude='.venv' \
    panel_bridge pyproject.toml README.md test_client.py || return 1

  # Resolve org/repo from origin once — substituted into install-pi.sh,
  # panel-update.sh, and any other scripts that reference __REPO__.
  local gh_repo
  gh_repo=$(_cr_gh_repo "$repo_root")
  if [[ -z "$gh_repo" ]]; then
    print -u2 "cut-release: couldn't parse github org/repo from origin remote"
    return 1
  fi

  # Deploy tarball — systemd units + runner scripts + sway config. Staged
  # to a temp tree first so we can substitute __REPO__ in scripts before
  # tarballing, leaving the source tree clean. install-pi.sh ships loose
  # at the release root, not in this tarball (chicken-and-egg: must be
  # downloadable before any /opt/panel/ exists).
  print ""
  print "→ panel-deploy..."
  local deploy_stage="$staging/.deploy-stage"
  rm -rf "$deploy_stage"
  mkdir -p "$deploy_stage"
  ( cd "$repo_root/platform/deploy" && \
    tar -cf - --exclude='install-pi.sh' --exclude='README.md' . ) \
    | tar -xf - -C "$deploy_stage" || return 1
  local f
  for f in "$deploy_stage"/*.sh; do
    [[ -f "$f" ]] || continue
    _cr_substitute_repo "$f" "$gh_repo" || return 1
  done
  tar -czf "$staging/panel-deploy-${bare_version}.tar.gz" \
    -C "$deploy_stage" . || return 1
  rm -rf "$deploy_stage"

  # Integration zip — content_in_root: true in hacs.json, so the zip
  # contains the integration files directly at root (manifest.json,
  # __init__.py, ...) with no wrapper directory. HACS reads the domain
  # field from manifest.json and places the files at
  # custom_components/<domain>/ on the HA box. Staged through a temp
  # tree so we can substitute __REPO__ in update.py (and any future
  # repo-aware integration source) before zipping, and so we can zip
  # from inside the directory to put files at root. Same pattern as
  # the deploy tarball above.
  print ""
  print "→ thread_panel integration..."
  local integ_stage="$staging/.integ-stage"
  rm -rf "$integ_stage"
  mkdir -p "$integ_stage"
  ( cd "$repo_root/platform/integration" && \
    tar -cf - --exclude='__pycache__' --exclude='*.pyc' thread_panel ) \
    | tar -xf - -C "$integ_stage" || return 1
  for f in "$integ_stage"/thread_panel/*.py; do
    [[ -f "$f" ]] || continue
    if grep -q "__REPO__" "$f" 2>/dev/null; then
      _cr_substitute_repo "$f" "$gh_repo" || return 1
    fi
  done
  ( cd "$integ_stage/thread_panel" && \
    zip -qr "$staging/thread_panel-${bare_version}.zip" . ) || return 1
  rm -rf "$integ_stage"

  # install-pi.sh shipped loose at the release root for `curl -L
  # .../releases/latest/download/install-pi.sh | bash` bootstrap. Same
  # __REPO__ substitution as the deploy tarball's scripts.
  print ""
  print "→ install-pi.sh..."
  cp "$repo_root/platform/deploy/install-pi.sh" "$staging/install-pi.sh" || return 1
  _cr_substitute_repo "$staging/install-pi.sh" "$gh_repo" || return 1
  chmod +x "$staging/install-pi.sh"

  # ----- manifest.json -----
  print ""
  print "→ manifest.json..."
  python3 - "$staging" "$new_version" "$bare_version" <<'PY'
import hashlib, json, os, pathlib, sys, datetime
staging, version, bare = sys.argv[1], sys.argv[2], sys.argv[3]
sd = pathlib.Path(staging)

def meta(path):
    h = hashlib.sha256()
    size = 0
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk); size += len(chunk)
    return {
        "filename": path.name,
        "size": size,
        "sha256": h.hexdigest(),
    }

components = {}
panels = {}
for f in sorted(sd.iterdir()):
    if not f.is_file() or f.name == "manifest.json":
        continue
    name = f.name
    # Per-panel: <panel_id>-firmware-<v>.bin or <panel_id>-ui-<v>.tar.gz
    if name == "install-pi.sh":
        # Loose bootstrap, not a versioned component — skip
        continue
    if name.startswith("panel-bridge-"):
        components["bridge"] = meta(f)
    elif name.startswith("panel-deploy-"):
        components["deploy"] = meta(f)
    elif name.startswith("thread_panel-"):
        components["integration"] = meta(f)
    elif "-firmware-" in name:
        panel_id = name.split("-firmware-")[0]
        panels.setdefault(panel_id, {})["firmware"] = meta(f)
    elif "-ui-" in name:
        panel_id = name.split("-ui-")[0]
        panels.setdefault(panel_id, {})["ui"] = meta(f)

doc = {
    "version": version,
    "released_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    "components": components,
    "panels": panels,
}
(sd / "manifest.json").write_text(json.dumps(doc, indent=2) + "\n")
PY

  # ----- release notes -----
  local notes_file="$staging/notes.md"
  {
    if [[ -n "$latest" ]]; then
      print "## Changes since $latest"
      print ""
      git -C "$repo_root" --no-pager log --pretty=format:'- %s (%h)' "$latest"..HEAD
      print ""
    else
      print "## Initial release"
    fi
    print ""
    print "## Artifacts"
    print ""
    print "Manifest in \`manifest.json\` lists sha256 + size per artifact. The"
    print "Pi installer downloads only what's needed; HACS pulls"
    print "\`thread_panel-${bare_version}.zip\` for the integration."
  } > "$notes_file"

  print ""
  print "Generated release notes:"
  print "─────────────────────────"
  cat "$notes_file"
  print "─────────────────────────"
  print ""

  if gum confirm "Edit notes before publishing?" --default=No; then
    ${EDITOR:-vi} "$notes_file"
  fi

  # ----- publish -----
  print ""
  print "Publishing release..."
  local gh_args=("$new_version" "--title" "$new_version" "--notes-file" "$notes_file")
  (( is_prerelease )) && gh_args+=("--prerelease")
  if ! gh release create "${gh_args[@]}" \
    "$staging"/*.bin "$staging"/*.tar.gz "$staging"/*.zip \
    "$staging/manifest.json" "$staging/install-pi.sh"; then
    print ""
    print -u2 "cut-release: gh release create failed."
    print ""
    local recovery
    recovery=$(gum choose --header "Cleanup options:" \
      "Roll back: delete tag (local + remote), delete partial release, prune staging" \
      "Keep state: leave tag + staging in place for manual recovery") || recovery="Keep state"
    case "$recovery" in
      Roll\ back*)
        print "→ Deleting tag from origin..."
        git -C "$repo_root" push --delete origin "$new_version" 2>/dev/null || true
        print "→ Deleting local tag..."
        git -C "$repo_root" tag -d "$new_version" 2>/dev/null || true
        print "→ Deleting GitHub release (if any)..."
        ( cd "$repo_root" && gh release delete "$new_version" --yes 2>/dev/null ) || true
        print "→ Removing staging dir..."
        rm -rf "$staging"
        print ""
        print "✓ Rolled back. Re-run cut-release to try again."
        ;;
      *)
        print -u2 "  Tag was pushed; artifacts are in $staging/."
        print -u2 "  Manual retry: gh release create ${(j: :)gh_args} \"$staging\"/*"
        ;;
    esac
    return 1
  fi

  # ----- success: clean up staging -----
  rm -rf "$staging"

  local origin repo_path
  origin=$(git -C "$repo_root" remote get-url origin 2>/dev/null || print "")
  if [[ "$origin" =~ 'github\.com[:/]([^/]+/[^/.]+)' ]]; then
    repo_path=${match[1]}
    print ""
    print "✓ Released ${new_version}"
    print "  https://github.com/$repo_path/releases/tag/$new_version"
  else
    print ""
    print "✓ Released ${new_version}"
  fi
}

# Allow running as a script too: `zsh tools/cut-release.zsh`
if [[ "${ZSH_EVAL_CONTEXT:-}" == *:file ]]; then
  : # sourced — expose the function
else
  cut-release "$@"
fi
