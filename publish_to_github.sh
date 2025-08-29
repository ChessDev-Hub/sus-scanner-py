#!/usr/bin/env bash
set -euo pipefail

# ====== CONFIG ======
ORG="chessdev-hub"
REPO="sus-scanner"             # change if you want another repo name
VISIBILITY="public"            # public|private|internal
DEFAULT_BRANCH="main"
DESCRIPTION="Chess.com Daily Suspicion Scanner – Tournament vs Non-Tournament analysis (Python + CLI)"
HOMEPAGE_URL=""
TOPICS="chess,selenium,cheating-detection,analytics,python,cli"
# =====================

# sanity
command -v git >/dev/null || { echo "git not found"; exit 1; }
command -v gh >/dev/null || { echo "GitHub CLI (gh) not found"; exit 1; }

# ensure we're at the project root (has at least one of these)
if [[ ! -f "pyproject.toml" && ! -f "setup.py" && ! -d "src" ]]; then
  echo "Run this inside your project root (where pyproject.toml/setup.py/src live)."
  exit 1
fi

# init git if needed
if [[ ! -d .git ]]; then
  git init -b "$DEFAULT_BRANCH"
  git add .
  git commit -m "Initial commit: SusScanner"
fi

# make sure default branch exists
git rev-parse --verify "$DEFAULT_BRANCH" >/dev/null 2>&1 || {
  git checkout -b "$DEFAULT_BRANCH"
}

# check if repo exists in org
if gh repo view "$ORG/$REPO" >/dev/null 2>&1; then
  echo "Repo $ORG/$REPO already exists. Linking remote and pushing..."
  git remote remove origin 2>/dev/null || true
  git remote add origin "https://github.com/$ORG/$REPO.git"
else
  echo "Creating repo $ORG/$REPO in org $ORG..."
  gh repo create "$ORG/$REPO" \
    --"$VISIBILITY" \
    --description "$DESCRIPTION" \
    ${HOMEPAGE_URL:+--homepage "$HOMEPAGE_URL"} \
    --disable-wiki \
    --confirm

  # set topics
  if [[ -n "$TOPICS" ]]; then
    gh repo edit "$ORG/$REPO" --add-topic $(echo "$TOPICS" | tr ',' ' ')
  fi

  # connect remote
  git remote add origin "https://github.com/$ORG/$REPO.git"
fi

# push
git push -u origin "$DEFAULT_BRANCH"

# optional: protect main branch (basic rules)
echo "Setting branch protection on $DEFAULT_BRANCH..."
gh api -X PUT \
  -H "Accept: application/vnd.github+json" \
  "/repos/$ORG/$REPO/branches/$DEFAULT_BRANCH/protection" \
  -f required_status_checks='{"strict":true,"contexts":[]}' \
  -f enforce_admins=true \
  -f required_pull_request_reviews='{"required_approving_review_count":1}' \
  -f restrictions='null' >/dev/null

echo "Done! Repo: https://github.com/$ORG/$REPO"
