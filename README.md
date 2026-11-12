<p align="center">
  <img src="assets/banner.svg" alt="dirxray - X-ray any folder" width="100%">
</p>

<p align="center">
  <img alt="Python 3.8+" src="https://img.shields.io/badge/python-3.8%2B-22d3ee?style=flat-square">
  <img alt="Zero dependencies" src="https://img.shields.io/badge/dependencies-0-a78bfa?style=flat-square">
  <img alt="Single file" src="https://img.shields.io/badge/single-file-4ade80?style=flat-square">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-94a3b8?style=flat-square">
</p>

**dirxray** scans any folder in a fraction of a second and tells you what's really inside: languages, duplicate files, leaked secrets, oversized files, and leftover task markers. It then gives the project a **health score** and can export a pretty, self-contained **HTML report**.

No `pip install`. No `npm`. No config. Just one Python file.

<p align="center">
  <img src="assets/terminal.svg" alt="dirxray terminal demo" width="100%">
</p>

## Quick start

```bash
# grab the single file...
curl -O https://raw.githubusercontent.com/ERROR404DTIR/dirxray/main/dirxray.py

# ...and run it on any folder
python dirxray.py ./my-project
```

Or clone it:

```bash
git clone https://github.com/ERROR404DTIR/dirxray.git
python dirxray/dirxray.py .
```

## What it finds

| Check | What it does |
| --- | --- |
| **Languages** | Lines of code per language, with bars |
| **Secrets** | AWS keys, GitHub/Slack/Google tokens, private keys, hardcoded passwords (values are masked in output) |
| **Duplicates** | Byte-identical files, grouped, with wasted space |
| **Big files** | Anything over 5 MB that probably doesn't belong in a repo |
| **Task markers** | TODO-style comments, with file and line |
| **Hygiene** | Missing README, LICENSE, or .gitignore |

Smart defaults: `.git`, `node_modules`, `venv`, `dist`, `build` and other noise folders are skipped, symlinks are ignored, and huge or binary files are never loaded into memory.

## Usage

```bash
python dirxray.py [path] [options]
```

| Option | Description |
| --- | --- |
| `--html FILE` | Write a self-contained, animated HTML report |
| `--open` | Write the report to `xray.html` and open it in your browser |
| `--json` | Print machine-readable JSON instead of the terminal report |
| `--top N` | Rows per section in the terminal (default 8) |
| `--fail-under N` | Exit with code 1 if the health score is below N |
| `--version` | Print the version |

Set `NO_COLOR=1` to disable terminal colors.

## Health score

Every folder starts at **100** and loses points for problems:

| Problem | Penalty |
| --- | --- |
| Possible secret | -8 each (max -40) |
| Duplicate files | by wasted space and group count (max -20) |
| Big file | -5 each (max -15) |
| Task-marker density | up to -10 |
| No README / LICENSE / .gitignore | -5 / -3 / -2 |

Grades: **A** 90+, **B** 80+, **C** 70+, **D** 60+, **F** below.

## Use it in CI

Fail a pipeline when a project's health drops:

```yaml
- uses: actions/checkout@v4
- run: python dirxray.py . --fail-under 80
```

## Why another scanner?

Most tools do one job (secrets *or* duplicates *or* line counts) and need an install. dirxray does the common checks together, runs anywhere Python runs, and stays small enough to read in one sitting.

## License

MIT. See [LICENSE](LICENSE).
