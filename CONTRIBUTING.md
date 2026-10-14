# Contributing to LeanStack

Thank you for your interest in contributing to LeanStack! We welcome pull requests, bug reports, and discussions to improve high-density autonomous WordPress hosting.

---

## Development & Testing Workflow

### 1. Prerequisites
* **OS:** Ubuntu 22.04 LTS, 24.04 LTS, or 26.04 LTS (x86_64)
* **Python:** 3.10+
* **Node.js:** 18+ (for building website CSS if modifying `site/`)

### 2. Local Setup
Clone your fork of the repository:
```bash
git clone https://github.com/YOUR_USERNAME/leanstack.git
cd leanstack
```

Install frontend build dependencies (optional, only needed for `site/` CSS changes):
```bash
npm install
```

### 3. Running the Test Suite
LeanStack enforces a 10-Pillar Master Verification Suite covering architecture decoupling, auto-tuning, caching logic, database isolation, WAF rules, and CLI integrity.

Before submitting any pull request, run:
```bash
bash tests/run_tests.sh
```
All 10 pillars must pass with a **100/100 (100% Readiness)** score.

---

## Pull Request Guidelines

1. **Branch Naming**: Use descriptive branch names:
   * `feature/hardware-probe-expansion`
   * `fix/valkey-socket-permissions`
   * `docs/troubleshooting-mariadb`
2. **Code Style**:
   * **Python:** Follow PEP 8 standards. Format with `black` or `ruff`.
   * **Bash:** Follow ShellCheck best practices (`set -euo pipefail`).
   * **CSS:** Compile changes using `npm run build:css`. Do not commit unminified debug stylesheets.
3. **Commit Messages**: Write concise, conventional commit messages:
   * `feat: add arm64 detection to hardware tuning probe`
   * `fix(angie): prevent duplicate SSL header inclusion`
   * `docs: update operations manual with migration guide`
4. **Documentation**: Update [README.md](README.md) and [docs/OPERATIONS_MANUAL.md](docs/OPERATIONS_MANUAL.md) if modifying CLI commands, configuration directives, or installation flags.

---

## Community & Discussions
Have an architectural idea or performance benchmark to share? Open a discussion in the **GitHub Discussions** tab!
