# Security

- Tokens are NEVER stored plaintext.
- Token envelope encryption uses AES-256-GCM + GCP KMS wrapped DEKs.
- Secret Manager stores runtime secrets such as connection strings and API keys.
- No credentials in source code, ever.

See design §9 in `sdd/zeler-platform-greenfield/design.md` for the security model.
