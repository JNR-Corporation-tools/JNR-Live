# Security Policy

## Supported releases

Security fixes target the current release line.

## Report a vulnerability

Please do not open a public issue for an undisclosed security problem. Contact the repository maintainer privately through the official JNR Corporations contact channel and include reproducible technical details.

## Security boundaries

Live Server is designed as a local development utility. The dashboard binds to localhost by default, sharing is opt-in, upstream targets are restricted to loopback, and the application does not expose arbitrary filesystem paths.

The repository also ships a release integrity manifest. It is a tamper-evidence feature, not a replacement for GitHub permissions or operating-system security.
