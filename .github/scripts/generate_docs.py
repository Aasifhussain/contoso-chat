import os
import subprocess
import glob
from pathlib import Path
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────
client        = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
DOCS_TOKEN    = os.environ["DOCS_REPO_TOKEN"]
DOCS_REPO     = os.environ["DOCS_REPO"]          # e.g. "your-org/product-docs"
DOCS_REPO_URL = f"https://x:{DOCS_TOKEN}@github.com/{DOCS_REPO}.git"
DOCS_DIR      = Path("_cloned_docs")             # local clone target
MODEL         = "gpt-5-nano"

# ── Git helpers ───────────────────────────────────────────────────────────────
def git(args: list[str], cwd=None):
    subprocess.run(
        ["git"] + args,
        cwd=cwd,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME":     os.environ.get("GIT_AUTHOR_NAME", "docs-bot"),
            "GIT_AUTHOR_EMAIL":    os.environ.get("GIT_AUTHOR_EMAIL", "docs-bot@users.noreply.github.com"),
            "GIT_COMMITTER_NAME":  os.environ.get("GIT_AUTHOR_NAME", "docs-bot"),
            "GIT_COMMITTER_EMAIL": os.environ.get("GIT_AUTHOR_EMAIL", "docs-bot@users.noreply.github.com"),
        },
    )

# ── LLM call ─────────────────────────────────────────────────────────────────
def generate(system_prompt: str, user_content: str) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
        max_completion_tokens=2000,
    )
    return response.choices[0].message.content.strip()

# ── Source readers ────────────────────────────────────────────────────────────
def read_src() -> str:
    """Concatenate all Python/JS/TS files under src/ (truncated to keep tokens low)."""
    files = glob.glob("src/**/*.py", recursive=True) + \
            glob.glob("src/**/*.ts", recursive=True) + \
            glob.glob("src/**/*.js", recursive=True)
    parts = []
    for f in sorted(files)[:20]:          # cap at 20 files
        content = Path(f).read_text(errors="ignore")[:3000]   # cap per file
        parts.append(f"### {f}\n{content}")
    return "\n\n".join(parts) or "No source files found."

def read_openapi() -> str:
    for candidate in ["openapi.yaml", "openapi.json", "api/openapi.yaml"]:
        p = Path(candidate)
        if p.exists():
            return p.read_text()
    return ""

def read_readme() -> str:
    for candidate in ["README.md", "README.rst"]:
        p = Path(candidate)
        if p.exists():
            return p.read_text()[:4000]
    return ""

# ── Generators ────────────────────────────────────────────────────────────────
def gen_overview(src: str) -> str:
    system = """You are a technical writer. Given source code, write a concise
product overview page in Mintlify MDX format. Include:
- A one-paragraph summary
- Key features as a bullet list
- A brief architecture note
Output raw MDX only — no code fences, no commentary."""
    return generate(system, f"Source code:\n{src}")


def gen_quickstart(readme: str) -> str:
    system = """You are a technical writer. Given a README, write a Quickstart
guide in Mintlify MDX format. Include:
- Prerequisites
- Installation steps (numbered)
- A minimal working example
- Environment variables table if present
Output raw MDX only — no code fences, no commentary."""
    return generate(system, f"README:\n{readme}")


def gen_changelog_entry(src: str) -> str:
    system = """You are a technical writer. Given source code, write ONE new
changelog entry using the Mintlify <Update> component format:

<Update date="YYYY-MM-DD" title="Brief title">
  Description of what changed.
</Update>

Use today's date. Output the <Update> block only — nothing else."""
    from datetime import date
    return generate(system, f"Today: {date.today()}\n\nSource:\n{src}")


def gen_api_overview(openapi: str) -> str:
    system = """You are a technical writer. Given an OpenAPI spec, write a
brief API Reference overview page in Mintlify MDX format. Include:
- Base URL
- Authentication method
- List of endpoint groups with one-line descriptions
Output raw MDX only — no code fences, no commentary."""
    return generate(system, f"OpenAPI spec:\n{openapi}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Reading source files...")
    src      = read_src()
    readme   = read_readme()
    openapi  = read_openapi()

    print("Generating docs with GPT-4o-mini...")
    results = {
        "guides/overview.mdx":   gen_overview(src),
        "quickstart.mdx":        gen_quickstart(readme) if readme else None,
        "changelog.mdx":         gen_changelog_entry(src),
    }
    if openapi:
        results["api-reference/overview.mdx"] = gen_api_overview(openapi)

    print(f"Cloning {DOCS_REPO}...")
    git(["clone", DOCS_REPO_URL, str(DOCS_DIR)])

    changed = False
    for rel_path, content in results.items():
        if content is None:
            continue
        dest = DOCS_DIR / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Only write if content actually changed
        existing = dest.read_text() if dest.exists() else ""
        if content != existing:
            dest.write_text(content)
            print(f"  Updated: {rel_path}")
            changed = True
        else:
            print(f"  No change: {rel_path}")

    if not changed:
        print("Nothing changed — skipping commit.")
        return

    git(["add", "."],                                         cwd=DOCS_DIR)
    git(["commit", "-m", "docs: AI-generated update [skip ci]"], cwd=DOCS_DIR)
    git(["push"],                                             cwd=DOCS_DIR)
    print("Pushed to docs repo. Mintlify will auto-deploy.")

if __name__ == "__main__":
    main()
