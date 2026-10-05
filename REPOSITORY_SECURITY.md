# GitHub Repository Security

> Important: a public Git clone is a copy. No local script can reliably prevent the owner of that copy from editing or deleting their own files. Do not use self-deleting code for repository protection.

## Recommended GitHub configuration

Protect `main` and require:

- Pull request before merge
- Required approving review
- Require review from Code Owners
- Required CI status checks
- No force pushes
- No branch deletion
- Require conversation resolution
- Require signed commits when your maintainer workflow supports them
- Apply the rules to administrators where available
- Restrict who can push to the protected branch when your organization plan supports it

Keep `.github/CODEOWNERS` itself owned by the maintainer. The included CODEOWNERS file uses `@Cyber-Yodhas`; change that handle if your maintainer account is different.

## Local integrity mode

Normal runs show a tamper-evidence warning when protected files differ from `integrity.json`.

Strict mode refuses to start:

```bash
python start.py --strict-integrity
```

This is an integrity check, not an access-control system. GitHub branch protection and repository permissions are the real control for the official repository.
