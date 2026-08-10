# Security

## Reporting

Report suspected secret leaks or unsafe automation to the project owner. Do not open public issues with credentials.

## Secrets

- Store Gemini keys only in local `.env` (gitignored).
- `.env.example` must contain placeholders only (`your_key_here`).
- CI must run without `GEMINI_API_KEY`.
- Traces must not record API keys, Authorization headers, or credential-bearing exceptions.

## Safety defaults

- `config/gemini.yaml` → `live_enabled: false`
- `config/corpus_snapshot.yaml` → `live_fetch_enabled: false`, `publish_enabled: false`
- Cross-user ticket access fails closed with non-disclosing messages
