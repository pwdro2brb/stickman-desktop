# Security policy

## Supported version

The latest version on the `main` branch receives security fixes.

## Reporting

Please report vulnerabilities privately to the repository owner. Do not open a public issue for a vulnerability that could enable arbitrary code execution or unauthorized file access.

## Security guarantees of the MVP

- Command text is not executed by a shell.
- Process launch is limited to `authorized_apps`.
- The project does not request administrator privileges.
- The project does not collect credentials.
- The project does not send telemetry or network requests.
- The project does not delete or modify user files.

## Out of scope

The project is experimental. It is not a security boundary and should not be used to run untrusted configuration files.
