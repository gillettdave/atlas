# Career memory — facts (free vs paid)

Authoritative product context: [UNIFIED_PRODUCT_PLAN.md](./UNIFIED_PRODUCT_PLAN.md).

## Free tier (default engine behavior)

**Ingestion** (`POST /career-memory/documents`, `POST /career-memory/documents/text`, `ingest_source_document` in `backend/app/services/career_memory.py`):

- Extracts plain text from PDF / Word / `.txt`.
- By default, builds **draft facts** with `_extract_candidate_facts`: non-empty lines with at least **five** whitespace-separated tokens that pass a readability heuristic, **up to 25 lines per document** (not the whole file).
- No LLM call unless you opt in (see below).

So structured or ChatGPT-authored “source of truth” documents often produce **noisy drafts** (headings, numbered sections, etc.) on the heuristic path. That is expected.

**Operator UX (Streamlit):** Profile → Career memory — **Draft fact extraction** selector at the top (server default / heuristic only / OpenAI). **Facts** tab — filter, paginate, **Approve** / **Reject** / **Edit** / **Delete** per row. After document ingest, the UI nudges you to open **Facts** and refresh. Deleted rows are removed via `DELETE /career-memory/facts/{id}`.

**Downstream use:** Exports and application-package generation generally prefer **approved** (and often **core proof point**) facts — see `application_packages` / `CareerFact` queries in `backend/app/services/application_packages.py`.

## Optional LLM-assisted draft facts (dogfood / BYOK)

**Implemented for source documents only** (not reference-docs ingest): when the ingest path is told to use LLM facts, the service calls `extract_candidate_facts_llm` (OpenAI via `get_chat_completer`). Draft rows get `source_trace` like `llm:<model-or-provider>` and a slightly higher `confidence_score` than heuristic drafts. If the model returns nothing, ingest **falls back** to `_extract_candidate_facts` and logs a warning.

**Tri-state flag**

| Client sends `llm_facts` | Behavior |
|--------------------------|----------|
| Omitted / `null` | Use **`ATLAS_CAREER_MEMORY_LLM_FACTS_DEFAULT`** (default `false`). |
| `false` | Heuristic lines only. |
| `true` | LLM path; requires a configured API key — otherwise **`400`** with a clear message. |

**HTTP**

- **`POST /career-memory/documents`** — optional multipart form field **`llm_facts`** (`true` / `false`).
- **`POST /career-memory/documents/text`** — optional JSON field **`llm_facts`** (boolean or null).

**Configuration (`ATLAS_` prefix)**

- `CAREER_MEMORY_LLM_FACTS_DEFAULT` — default when the client omits the flag.
- `CAREER_MEMORY_LLM_FACTS_MAX_INPUT_CHARS` — cap on text sent to the model (default 48_000).
- `CAREER_MEMORY_LLM_FACTS_MAX_ITEMS` — max facts accepted from the model (default 40).

OpenAI (or provider) keys and model id follow existing app settings (e.g. `OPENAI_API_KEY` / `ATLAS_OPENAI_API_KEY` depending on your config module).

## Paid tier (planned — product gate)

**Not implemented as a subscription gate yet.** Intended direction: feature flag + subscription check (or BYOK) before running the LLM path in production; free deployments stay heuristic-by-default. Cost controls (tokens, rate limits, UI cost hints) TBD.

## Related API routes

| Route | Role |
|-------|------|
| `GET /career-memory/facts` | List facts (includes `source_document_id` in responses) |
| `PATCH /career-memory/facts/{id}` | Edit text, `verification_state`, `is_core_proof_point` |
| `DELETE /career-memory/facts/{id}` | Permanent delete (tenant-scoped) |
| `POST /career-memory/facts/cleanup` | Heuristic rejection of unreadable drafts |

## Changelog

| Date | Change |
|------|--------|
| 2026-05-12 | Document free vs paid; Streamlit facts workbench + `DELETE` fact route. |
| 2026-05-12 | Optional LLM draft facts on ingest; env + `llm_facts` form/JSON; Streamlit selector. |
