# Security

## Supported version

Security fixes target the latest released SceneCraft version.

## Reporting

Do not publish exploitable path traversal, arbitrary code execution, unsafe Blender operation, secret exposure, or artifact-integrity issues in a public issue. Contact the repository owner privately through the security reporting channel configured on the GitHub repository.

Include the affected version, reproduction steps, impact, and any relevant job/result artifacts with private content removed.

## Trust model

SceneCraft treats model output and project JSON as untrusted data. The runtime accepts only versioned contracts, confines paths to the project root, invokes a repository-owned Blender runner, verifies result identity and artifact hashes, and never evaluates model-produced Python or shell text.
