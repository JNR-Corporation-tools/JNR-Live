# Contributing

Live Server is maintained as a controlled JNR Corporations project. The repository's `main` branch should be treated as a protected release branch.

## Development

Use the terminal-based bootstrap:

```bash
python3 start.py
```

Windows PowerShell:

```powershell
py start.py
```

Run checks before opening a pull request:

```bash
python verify_integrity.py
python -m unittest discover -s tests -v
```

## Protected release files

Changes to core runtime, security, frontend, dependency and integrity files should be reviewed by the configured CODEOWNER. GitHub branch protection/rulesets should require pull requests, passing CI, and code-owner approval for `main`.

Local clones can always be edited by their owners; GitHub permissions protect the official repository and its protected branches.
