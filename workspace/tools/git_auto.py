#!/usr/bin/env python3
"""Elysia Git Automation - fork repos, write code, push to git automatically."""
import subprocess, os, json, time, re
from pathlib import Path

WORKSPACE = "/data/elysia/workspace"
REPOS_DIR = os.path.join(WORKSPACE, "repos")
os.makedirs(REPOS_DIR, exist_ok=True)

class GitAutomation:
    def __init__(self):
        self._ensure_git_config()

    def _ensure_git_config(self):
        result = subprocess.run(['git', 'config', 'user.name'], capture_output=True, text=True)
        if not result.stdout.strip():
            subprocess.run(['git', 'config', '--global', 'user.name', 'Elysia AI Agent'], capture_output=True)
            subprocess.run(['git', 'config', '--global', 'user.email', 'elysia@ai.local'], capture_output=True)

    def _run(self, cmd, cwd=None):
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=120)
        return result.stdout.strip(), result.stderr.strip(), result.returncode

    def init_repo(self, name):
        """Initialize a new git repository."""
        repo_dir = os.path.join(REPOS_DIR, name)
        os.makedirs(repo_dir, exist_ok=True)
        self._run('git init', cwd=repo_dir)
        return {'path': repo_dir, 'status': 'initialized'}

    def create_readme(self, repo_name, content="# Project\n\nBuilt by Elysia AI"):
        """Create a README.md in the repo."""
        repo_dir = os.path.join(REPOS_DIR, repo_name)
        readme_path = os.path.join(repo_dir, 'README.md')
        with open(readme_path, 'w') as f:
            f.write(content)
        return {'file': readme_path}

    def create_file(self, repo_name, filename, content):
        """Create a file in the repo."""
        repo_dir = os.path.join(REPOS_DIR, repo_name)
        filepath = os.path.join(repo_dir, filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w') as f:
            f.write(content)
        return {'file': filepath}

    def commit(self, repo_name, message="Auto-commit by Elysia"):
        """Stage all changes and commit."""
        repo_dir = os.path.join(REPOS_DIR, repo_name)
        self._run('git add -A', cwd=repo_dir)
        out, err, code = self._run(f'git commit -m "{message}"', cwd=repo_dir)
        return {'commit': message, 'output': out, 'error': err, 'code': code}

    def push(self, repo_name, remote="origin", branch="main"):
        """Push to remote."""
        repo_dir = os.path.join(REPOS_DIR, repo_name)
        out, err, code = self._run(f'git push {remote} {branch}', cwd=repo_dir)
        return {'output': out, 'error': err, 'code': code}

    def fork_and_clone(self, repo_url, new_name=None):
        """Clone a repo and optionally rename it."""
        repo_name = new_name or repo_url.split('/')[-1].replace('.git', '')
        repo_dir = os.path.join(REPOS_DIR, repo_name)
        out, err, code = self._run(f'git clone {repo_url} {repo_dir}')
        return {'path': repo_dir, 'output': out, 'error': err, 'code': code}

    def create_branch(self, repo_name, branch_name):
        """Create and switch to a new branch."""
        repo_dir = os.path.join(REPOS_DIR, repo_name)
        out, err, code = self._run(f'git checkout -b {branch_name}', cwd=repo_dir)
        return {'branch': branch_name, 'output': out, 'error': err, 'code': code}

    def merge_branch(self, repo_name, branch_name):
        """Merge a branch into current."""
        repo_dir = os.path.join(REPOS_DIR, repo_name)
        out, err, code = self._run(f'git merge {branch_name}', cwd=repo_dir)
        return {'output': out, 'error': err, 'code': code}

    def log(self, repo_name, count=10):
        """Get recent commit history."""
        repo_dir = os.path.join(REPOS_DIR, repo_name)
        out, _, _ = self._run(f'git log --oneline -{count}', cwd=repo_dir)
        return out.splitlines()

    def status(self, repo_name):
        """Get repo status."""
        repo_dir = os.path.join(REPOS_DIR, repo_name)
        out, _, _ = self._run('git status --short', cwd=repo_dir)
        return out.splitlines()

    def diff(self, repo_name):
        """Get current diff."""
        repo_dir = os.path.join(REPOS_DIR, repo_name)
        out, _, _ = self._run('git diff', cwd=repo_dir)
        return out

    def auto_commit_and_push(self, repo_name, message="Auto-update by Elysia"):
        """Full auto workflow: add, commit, push."""
        self.commit(repo_name, message)
        push_result = self.push(repo_name)
        return push_result

    def scaffold_project(self, name, project_type="python"):
        """Create a project scaffold and commit it."""
        self.init_repo(name)
        if project_type == "python":
            self.create_file(name, 'main.py', '#!/usr/bin/env python3\n\nif __name__ == "__main__":\n    print("Hello from Elysia")\n')
            self.create_file(name, 'requirements.txt', '')
            self.create_file(name, '.gitignore', '__pycache__/\n*.pyc\n.env\nvenv/\n')
            self.create_readme(name, f"# {name}\n\nPython project built by Elysia AI.\n")
        elif project_type == "node":
            self.create_file(name, 'index.js', 'console.log("Hello from Elysia");\n')
            self.create_file(name, 'package.json', json.dumps({"name": name, "version": "1.0.0"}, indent=2))
            self.create_file(name, '.gitignore', 'node_modules/\n.env\n')
            self.create_readme(name, f"# {name}\n\nNode.js project built by Elysia AI.\n")
        elif project_type == "go":
            self.create_file(name, 'main.go', f'package main\n\nimport "fmt"\n\nfunc main() {{\n    fmt.Println("Hello from Elysia")\n}}\n')
            self.create_file(name, 'go.mod', f'module {name}\n\ngo 1.21\n')
            self.create_file(name, '.gitignore', 'vendor/\n.env\n')
            self.create_readme(name, f"# {name}\n\nGo project built by Elysia AI.\n")
        self.commit(name, f"Initial scaffold for {name}")
        return {'repo': name, 'type': project_type, 'status': 'scaffolded'}

    def build_and_test(self, repo_name, build_cmd="python3 main.py"):
        """Run build/test command and commit results."""
        repo_dir = os.path.join(REPOS_DIR, repo_name)
        out, err, code = self._run(build_cmd, cwd=repo_dir)
        return {'output': out, 'error': err, 'exit_code': code}

    def list_repos(self):
        """List all repos."""
        repos = []
        for d in os.listdir(REPOS_DIR):
            if os.path.isdir(os.path.join(REPOS_DIR, d, '.git')):
                repos.append(d)
        return repos

if __name__ == "__main__":
    import sys
    git = GitAutomation()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    if cmd == "scaffold":
        name = sys.argv[2] if len(sys.argv) > 2 else "my_project"
        ptype = sys.argv[3] if len(sys.argv) > 3 else "python"
        print(git.scaffold_project(name, ptype))
    elif cmd == "commit":
        name = sys.argv[2] if len(sys.argv) > 2 else "my_project"
        msg = ' '.join(sys.argv[3:]) if len(sys.argv) > 3 else "Auto-commit"
        print(git.commit(name, msg))
    elif cmd == "push":
        name = sys.argv[2] if len(sys.argv) > 2 else "my_project"
        print(git.push(name))
    elif cmd == "list":
        for r in git.list_repos():
            print(f"  {r}")
    elif cmd == "status":
        name = sys.argv[2] if len(sys.argv) > 2 else "my_project"
        for line in git.status(name):
            print(f"  {line}")
    elif cmd == "log":
        name = sys.argv[2] if len(sys.argv) > 2 else "my_project"
        for line in git.log(name):
            print(f"  {line}")
