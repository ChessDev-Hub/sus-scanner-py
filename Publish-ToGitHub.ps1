Param(
  [string]$Org = "chessdev-hub",
  [string]$Repo = "sus-scanner",
  [string]$Visibility = "public",  # public|private|internal
  [string]$DefaultBranch = "main",
  [string]$Description = "Chess.com Daily Suspicion Scanner – Tournament vs Non-Tournament analysis (Python + CLI)"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git not found" }
if (-not (Get-Command gh -ErrorAction SilentlyContinue))  { throw "GitHub CLI (gh) not found" }

if (-not (Test-Path "pyproject.toml") -and -not (Test-Path "setup.py") -and -not (Test-Path "src")) {
  throw "Run this inside your project root (where pyproject.toml/setup.py/src live)."
}

if (-not (Test-Path ".git")) {
  git init -b $DefaultBranch
  git add .
  git commit -m "Initial commit: SusScanner"
}

# ensure default branch exists
try { git rev-parse --verify $DefaultBranch | Out-Null } catch { git checkout -b $DefaultBranch }

# does repo already exist?
$exists = $false
try { gh repo view "$Org/$Repo" | Out-Null; $exists = $true } catch { $exists = $false }

if ($exists) {
  Write-Host "Repo $Org/$Repo exists. Linking remote and pushing..."
  try { git remote remove origin } catch {}
  git remote add origin "https://github.com/$Org/$Repo.git"
} else {
  Write-Host "Creating repo $Org/$Repo in org $Org..."
  gh repo create "$Org/$Repo" --$Visibility --description $Description --disable-wiki --confirm
  git remote add origin "https://github.com/$Org/$Repo.git"
}

git push -u origin $DefaultBranch

Write-Host "Done! Repo: https://github.com/$Org/$Repo"
