<# 
  Setup-And-CheckIn.ps1
  Initializes a Git repo in the current folder (if needed), creates/links a GitHub repo
  in your org, pushes code, creates labels, optionally applies branch protection,
  and can open a PR.

  Requires: Git, GitHub CLI (`gh`) authenticated.
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$Org,                    # e.g. ChessDev-Hub
  [Parameter(Mandatory=$true)][string]$Repo,                   # e.g. sus-scanner or sus-scanner-api
  [string]$Description = "Auto-created by Setup-And-CheckIn.ps1",
  [switch]$Private,                                            # create as private repo
  [string]$BaseBranch = "main",
  [string]$FeatureBranch = "",                                 # if empty with -OpenPR, will generate feat/*

  [Parameter(Mandatory=$true)][string]$CommitMessage,

  # Actions
  [switch]$CreateRepo,                                         # create GH repo if missing
  [switch]$InitGit,                                            # git init if not present
  [switch]$OpenPR,                                             # create a PR into $BaseBranch
  [switch]$ApplyBranchProtection,                              # set protection rules (see also -RequireCI)
  [switch]$RequireCI,                                          # include "CI" as required status check

  # Decorations
  [string[]]$Labels = @("automation","needs-review"),
  [string[]]$Topics = @("sus-scanner","chess","fastapi","react","tailwind"),

  # PR metadata
  [string]$PrTitle = "",
  [string]$PrBody  = "Automated PR via Setup-And-CheckIn.ps1",
  [string[]]$Reviewers = @(),
  [switch]$DraftPR
)

function Fail($msg) { Write-Error $msg; exit 1 }

# --- Pre-flight checks ---
git --version *> $null 2>&1; if ($LASTEXITCODE -ne 0) { Fail "git not found. Install Git first." }
gh --version  *> $null 2>&1; if ($LASTEXITCODE -ne 0) { Fail "GitHub CLI (gh) not found. Install and run 'gh auth login'." }

$FullRepo = "$Org/$Repo"
$originUrl = "https://github.com/$FullRepo.git"
Write-Host "==> Target: $FullRepo`n"

# --- Local git init/link ---
$IsGitRepo = Test-Path ".git"
if ($InitGit -and -not $IsGitRepo) {
  Write-Host "Initializing local Git repository..."
  git init                         || Fail "git init failed"
  git checkout -B $BaseBranch      || Fail "git checkout -B $BaseBranch failed"
}

if (-not (Test-Path ".git")) {
  Write-Host "No .git folder found. Initializing..."
  git init                         || Fail "git init failed"
  git checkout -B $BaseBranch      || Fail "git checkout -B $BaseBranch failed"
}

# --- Create repo if requested ---
if ($CreateRepo) {
  Write-Host "Creating repo $FullRepo (if missing)..."
  $vis = $Private.IsPresent ? "private" : "public"
  $repoExists = $false
  try {
    gh repo view $FullRepo --json name 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) { $repoExists = $true }
  } catch { $repoExists = $false }

  if (-not $repoExists) {
    # Creates only if missing; safe to call when missing
    gh repo create $FullRepo --$vis --description $Description --source "." --remote "origin" --push `
      || Fail "gh repo create failed."
    Write-Host "✅ Created and pushed repository $FullRepo"
  } else {
    Write-Host "Repo already exists."
    # IDEMPOTENT: link/set origin if needed (re-running won't duplicate)
    $currentRemote = ""
    try { $currentRemote = (git remote get-url origin 2>$null) } catch {}
    if (-not $currentRemote) {
      git remote add origin $originUrl || Fail "Failed to add remote origin"
    } elseif ($currentRemote -ne $originUrl) {
      git remote set-url origin $originUrl || Fail "Failed to update remote origin"
    } else {
      Write-Host "Origin already points to $originUrl (IDEMPOTENT)."
    }
  }

  # IDEMPOTENT: topics (re-applying just ensures topics are present)
  if ($Topics.Count -gt 0) {
    try {
      gh repo edit $FullRepo --add-topic ($Topics -join ",") | Out-Null
      Write-Host "Topics ensured (IDEMPOTENT): $($Topics -join ', ')"
    } catch {
      Write-Warning "Could not set topics."
    }
  }
} else {
  # IDEMPOTENT: ensure remote origin exists/correct
  $currentRemote = ""
  try { $currentRemote = (git remote get-url origin 2>$null) } catch {}
  if (-not $currentRemote) {
    git remote add origin $originUrl || Fail "Failed to add remote origin"
    Write-Host "Added origin $originUrl"
  } elseif ($currentRemote -ne $originUrl) {
    git remote set-url origin $originUrl || Fail "Failed to update remote origin"
    Write-Host "Updated origin to $originUrl"
  } else {
    Write-Host "Origin already points to $originUrl (IDEMPOTENT)."
  }
}

# --- Ensure base branch available locally ---
git fetch origin 1>$null 2>$null
$haveRemoteBase = $false
try {
  git ls-remote --exit-code --heads origin $BaseBranch 1>$null 2>$null
  if ($LASTEXITCODE -eq 0) { $haveRemoteBase = $true }
} catch {}

if ($haveRemoteBase) {
  git checkout -B $BaseBranch "origin/$BaseBranch" 2>$null `
    || git checkout -B $BaseBranch `
    || Fail "Checkout $BaseBranch failed"
  git pull --ff-only origin $BaseBranch 1>$null 2>$null
} else {
  git checkout -B $BaseBranch 1>$null 2>$null || Fail "Create local $BaseBranch failed"
}

# --- Labels ---
if ($Labels.Count -gt 0) {
  foreach ($label in $Labels) {
    # IDEMPOTENT: create if missing; otherwise edit to ensure it exists
    try {
      gh label create $label --repo $FullRepo 1>$null 2>$null
      Write-Host "Created label '$label'"
    } catch {
      try {
        gh label edit $label --repo $FullRepo 1>$null 2>$null
        Write-Host "Ensured label '$label' exists (IDEMPOTENT)"
      } catch {
        Write-Warning "Could not ensure label '$label'"
      }
    }
  }
}

# --- Add, commit ---
git add -A
if (git diff --cached --quiet) {
  Write-Host "No staged changes. Nothing to commit."
} else {
  git commit -m $CommitMessage || Fail "Commit failed"
}

# --- Push or feature PR ---
if ($OpenPR) {
  if (-not $FeatureBranch) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $slug  = ($CommitMessage -replace '[^a-zA-Z0-9\- ]','' -replace '\s+','-').ToLower()
    if ($slug.Length -gt 40) { $slug = $slug.Substring(0,40) }
    $FeatureBranch = "feat/$stamp-$slug"
  }
  git checkout -B $FeatureBranch || Fail "Create/switch to $FeatureBranch failed"
  git push -u origin $FeatureBranch || Fail "Push feature branch failed"
} else {
  # May fail if $BaseBranch is protected (that’s okay by design)
  git push -u origin $BaseBranch || Write-Warning "Push to $BaseBranch failed (branch may be protected). Consider -OpenPR."
}

# --- Branch protection ---
if ($ApplyBranchProtection) {
  Write-Host "Applying branch protection to $BaseBranch ..."
  # IDEMPOTENT: PUT of same policy simply ensures the settings remain as declared
  $contexts = @()
  if ($RequireCI) { $contexts += "CI" }   # must match GH Actions job name

  $bodyObj = @{
    required_status_checks = $(if ($RequireCI) @{ strict = $true; contexts = $contexts } else $null)
    enforce_admins = $true
    required_pull_request_reviews = @{
      required_approving_review_count = 1
    }
    restrictions = $null
  }
  $jsonBody = $bodyObj | ConvertTo-Json -Depth 6

  gh api -X PUT `
    -H "Accept: application/vnd.github+json" `
    "/repos/$FullRepo/branches/$BaseBranch/protection" `
    --input -  <<< $jsonBody  `
    || Write-Warning "Failed to apply branch protection."
  Write-Host "Branch protection ensured (IDEMPOTENT)."
}

# --- Create PR ---
if ($OpenPR) {
  if (-not $PrTitle) { $PrTitle = $CommitMessage }
  $args = @(
    "pr","create",
    "--repo",$FullRepo,
    "--base",$BaseBranch,
    "--head",$FeatureBranch,
    "--title",$PrTitle,
    "--body",$PrBody
  )
  if ($DraftPR) { $args += "--draft" }

  $prUrl = ""
  try {
    $prUrl = (gh @args).Trim()
  } catch {
    $prUrl = (gh pr view --repo $FullRepo --head $FeatureBranch --json url -q ".url" 2>$null)
  }

  if ($prUrl) {
    Write-Host "`nPR: $prUrl"
    # IDEMPOTENT: adding labels to an issue/PR that already has them is safe
    if ($Labels.Count -gt 0) {
      try {
        gh issue edit ($prUrl.Split('/')[-1]) --repo $FullRepo --add-label ($Labels -join ",") | Out-Null
        Write-Host "PR labels ensured (IDEMPOTENT): $($Labels -join ', ')"
      } catch { Write-Warning "Could not add PR labels." }
    }
    if ($Reviewers.Count -gt 0) {
      try {
        gh pr edit $prUrl --repo $FullRepo --add-reviewer ($Reviewers -join ",") | Out-Null
        Write-Host "Reviewers requested: $($Reviewers -join ', ')"
      } catch { Write-Warning "Could not request reviewers." }
    }
  } else {
    Write-Warning "PR create/view failed."
  }
}

Write-Host "`n✅ Done."
