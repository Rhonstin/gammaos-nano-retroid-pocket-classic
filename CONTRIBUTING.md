# Contributing

Run `python3 -m unittest discover -s tests -v` and
`python3 tools/check_repository.py` before submitting changes. Preparing the
pinned reference image enables the two actual-library NFS checks.

Keep release integration tied to exact input hashes. Explain which board,
vendor/kernel and runtime path a change affects, and distinguish source patches,
host tests and real device observations. Include only the validation needed to
establish the changed behavior; do not infer hardware success from CI.

Do not commit images, ROMs, saves, device backups, credentials or raw diagnostic
logs. New runtime captures belong in ignored `evidence/`; publish a reviewed,
redacted result summary. Preserve existing source notices and upstream attribution.

