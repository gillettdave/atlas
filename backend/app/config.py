"""Runtime configuration, loaded from environment / .env.

All env vars are prefixed with ATLAS_ to avoid collisions and keep ops readable.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        env_prefix="ATLAS_",
        case_sensitive=False,
        extra="ignore",
    )

    env: str = Field(default="dev")
    log_level: str = Field(default="INFO")

    database_url: str = Field(
        default="postgresql+psycopg://atlas:atlas@localhost:5432/atlas",
        description="SQLAlchemy URL. Must be PostgreSQL. No SQLite.",
    )

    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)

    # Parent of /backend; used to resolve `scripts/foo.csv` paths for collectors.
    repo_root: str | None = Field(default=None, description="Absolute path to repo root.")

    admin_token: str = Field(default="changeme-local-only")

    # --- Auth: Google OAuth + HS256 API bearer JWTs ---------------------
    jwt_secret: str | None = Field(
        default=None,
        description="HS256 secret for Atlas access tokens and OAuth state (min 16 chars when set).",
    )
    jwt_access_token_expires_seconds: int = Field(
        default=604_800,
        ge=300,
        le=31_536_000,
        description="Atlas API bearer JWT lifetime (OAuth callback mints).",
    )
    google_oauth_client_id: str | None = Field(default=None)
    google_oauth_client_secret: str | None = Field(default=None)
    google_oauth_redirect_uri: str | None = Field(
        default=None,
        description="Must exactly match redirect URI configured in Google Cloud Console.",
    )
    frontend_oauth_success_url: str | None = Field(
        default="http://127.0.0.1:8501/",
        description=(
            "After Google login, redirect browser here with ?atlas_token=<jwt> "
            "(Streamlit default)."
        ),
    )
    auth_allow_seeded_without_bearer: bool = Field(
        default=True,
        description=(
            "When true and no Authorization header, use SEEDED_LOCAL_USER_ID (dev parity). "
            "Set false in production to require Bearer."
        ),
    )

    # --- AI (Jobr-era features port; BYOK/hosted layering later) -----
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key for LLM-assisted features when set.",
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="Default model id for Chat Completions.",
    )

    packages_ai_enabled: bool = Field(
        default=False,
        description=(
            "When true, generate_application_package uses OpenAI to write the actual "
            "resume and cover letter instead of the scaffold template. "
            "Requires ATLAS_OPENAI_API_KEY. Falls back to template if AI call fails."
        ),
    )

    career_memory_llm_facts_default: bool = Field(
        default=False,
        description=(
            "When true, career document ingests use LLM fact extraction when the request does "
            "not pass llm_facts (multipart/JSON) and ATLAS_OPENAI_API_KEY is set."
        ),
    )
    career_memory_llm_facts_max_input_chars: int = Field(
        default=48_000,
        ge=4_000,
        le=200_000,
        description="Max characters of document text sent to the model for fact extraction.",
    )
    career_memory_llm_facts_max_items: int = Field(
        default=40,
        ge=1,
        le=200,
        description="Max draft facts inserted from one LLM response.",
    )

    # --- Jobr email intake port (optional IMAP; env ATLAS_GMAIL_* ) ------------
    gmail_imap_host: str = Field(default="imap.gmail.com")
    gmail_imap_port: int = Field(default=993, ge=1, le=65535)
    gmail_imap_username: str = Field(default="", description="Gmail/IMAP username when using email intake.")
    gmail_imap_password: str = Field(
        default="",
        description="App password / token for Gmail IMAP (store in env/secrets only).",
    )

    # --- Sprint H: scheduler loop -------------------------------------
    scheduler_enabled: bool = Field(
        default=False,
        description=(
            "When true, uvicorn starts a background task that calls "
            "services.scheduler.tick() every scheduler_interval_seconds."
        ),
    )
    scheduler_interval_seconds: int = Field(
        default=60,
        ge=10,
        le=3600,
        description="How often the background loop calls tick().",
    )
    scheduler_max_per_tick: int = Field(
        default=25,
        ge=1,
        le=200,
        description="Upper bound on schedules processed per tick pass.",
    )

    delivery_schedule_digest_build_extra_attempts: int = Field(
        default=1,
        ge=0,
        le=5,
        description=(
            "Transient-looking digest build failures (run_schedule) get this many extra "
            "tries with backoff before marking the schedule run as error."
        ),
    )
    delivery_schedule_channel_send_extra_attempts: int = Field(
        default=2,
        ge=0,
        le=10,
        description=(
            "Extra Slack/email deliver() attempts after a failed send (same digest id; "
            "does not rebuild the digest)."
        ),
    )
    delivery_schedule_retry_backoff_seconds: float = Field(
        default=20.0,
        ge=0.0,
        le=600.0,
        description="Base delay multiplied by attempt index between delivery run retries.",
    )
    delivery_schedule_error_retry_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=86_400.0,
        description=(
            "After a failed schedule run, if the error looks transient and this is >0, "
            "set next_run_at to min(normal next fire, now + this) so tick retries sooner "
            "without POST …/run-now. 0 = always use normal cadence only."
        ),
    )

    # --- Sprint M.1: collector schedule loop (same pattern as H) ----
    collector_scheduler_enabled: bool = Field(
        default=False,
        description=(
            "When true, uvicorn runs a second background loop that ticks "
            "collector_schedules (collect + import + rank)."
        ),
    )
    collector_scheduler_interval_seconds: int = Field(
        default=120,
        ge=30,
        le=3600,
        description="How often the collector tick runs.",
    )
    collector_scheduler_max_per_tick: int = Field(
        default=2,
        ge=1,
        le=50,
        description="Max collector schedules to process per tick (each may be slow).",
    )

    # --- Intake: discovery + email run-due loop (E3) ----------------------------
    intake_scheduler_enabled: bool = Field(
        default=False,
        description=(
            "When true, uvicorn runs a background loop that runs due discovery seeds "
            "and due email sync sources (same work as POST /discovery/run-due and "
            "POST /email/run-due)."
        ),
    )
    intake_scheduler_interval_seconds: int = Field(
        default=300,
        ge=60,
        le=7200,
        description="How often the intake scheduler tick runs.",
    )
    intake_scheduler_max_discovery_per_tick: int = Field(
        default=5,
        ge=0,
        le=50,
        description="Max discovery seed runs per tick (0 = skip discovery in this loop).",
    )
    intake_scheduler_max_email_per_tick: int = Field(
        default=3,
        ge=0,
        le=30,
        description="Max Gmail IMAP syncs per tick (0 = skip email; each can be slow).",
    )

    # --- Sprint M.3: Jobstash aggregator --------------------------------
    jobstash_sitemap_max_jobs: int = Field(
        default=80,
        ge=1,
        le=20_000,
        description=(
            "Target max RawCollectedRecord rows emitted in sitemap+JSON-LD mode "
            "(after date filter)."
        ),
    )
    jobstash_sitemap_discovery_max_urls: int = Field(
        default=2500,
        ge=50,
        le=25_000,
        description=(
            "How many two-segment job URLs to collect from Jobstash shard sitemaps "
            "before fetching HTML — higher improves chances of hitting recent postings "
            "when date filtering is tight."
        ),
    )
    jobstash_sitemap_request_gap_seconds: float = Field(
        default=0.65,
        ge=0.0,
        le=10.0,
        description="Polite delay between public HTML fetches.",
    )
    jobstash_sitemap_max_shards: int = Field(
        default=12,
        ge=1,
        le=64,
        description="How many shard sitemap XMLs (from the root sitemap index) to crawl per run.",
    )
    jobstash_initial_max_age_days: int = Field(
        default=14,
        ge=1,
        le=90,
        description="Public sitemap+JSON-LD: keep listings with datePosted within this many days (initial profile).",
    )
    jobstash_incremental_max_age_hours: float = Field(
        default=24.0,
        ge=1.0,
        le=168.0,
        description="Public sitemap+JSON-LD: incremental profile keeps postings newer than this many hours.",
    )
    jobstash_pull_profile: Literal["initial", "incremental"] = Field(
        default="incremental",
        description=(
            "initial ≈ postings not older than 14 days on first ingestion; "
            "incremental ≈ postings from the last day for scheduled daily pulls."
        ),
    )
    jobstash_api_base: str | None = Field(
        default=None,
        description=(
            "Optional Jobstash Middleware base URL "
            "(e.g. …/jobs/list). Leave unset to use public sitemap mode."
        ),
    )
    jobstash_api_bearer_token: str | None = Field(
        default=None,
        description="Bearer token when partner middleware auth is required.",
    )
    jobstash_api_page_size: int = Field(
        default=20,
        ge=1,
        le=20,
        description="Middleware /jobs/list page size — hard-capped at 20 per upstream guidance.",
    )
    jobstash_api_max_pages: int = Field(default=25, ge=1, le=500)
    jobstash_api_request_backoff_seconds: float = Field(
        default=0.75,
        ge=0.25,
        le=30.0,
        description="Base delay between API page requests (/jobs/list).",
    )
    jobstash_api_request_jitter_seconds: float = Field(
        default=0.35,
        ge=0.0,
        le=15.0,
        description="Random extra delay (uniform 0–jitter) added to backoff between API pages.",
    )
    jobstash_api_publication_date: str | None = Field(
        default=None,
        description=(
            "Override middleware publicationDate parameter (unset = derive from pull_profile: "
            "initial → past-2-weeks, incremental → today)."
        ),
    )

    # --- Importer / cleaner quality --------------------------------------------
    intake_max_listing_age_days: int | None = Field(
        default=None,
        description=(
            "If set (e.g. 30), reject **new canonical** jobs when a listing date can be parsed "
            "from raw_payload and is older than this many days. Unknown dates are not rejected. "
            "Unset = no global age gate (use per-collector settings such as Jobstash)."
        ),
    )

    # --- Sprint M.4: HTTP resilience — native ATS GETs -----------------------------
    http_retry_max_attempts: int = Field(
        default=5,
        ge=1,
        le=14,
        description="Max attempts per URL for collector ``http_utils.http_get`` (429/backoff loop).",
    )
    http_retry_base_seconds: float = Field(default=0.85, ge=0.1, le=25.0)
    http_retry_max_backoff_seconds: float = Field(
        default=60.0,
        ge=5.0,
        le=300.0,
        description="Clamp for exponential backoff + Retry-After cap.",
    )
    http_timeout_connect_seconds: float = Field(default=12.0, ge=4.0, le=120.0)
    http_timeout_read_seconds: float = Field(default=50.0, ge=10.0, le=240.0)
    smartrecruiters_page_pause_seconds: float = Field(
        default=0.45,
        ge=0.0,
        le=30.0,
        description="Polite pause between SmartRecruiters paginated GETs.",
    )

    # --- Automated collector pipeline / schedule (retry policy) -------------
    collector_pipeline_http_max_attempts: int = Field(
        default=5,
        ge=1,
        le=14,
        description="Retries per outbound API call inside collector_pipeline (httpx to same API).",
    )
    collector_pipeline_http_base_seconds: float = Field(default=0.85, ge=0.1, le=25.0)
    collector_pipeline_http_max_wait_seconds: float = Field(
        default=45.0,
        ge=5.0,
        le=180.0,
        description="Max sleep between retries for collector_pipeline HTTP helpers.",
    )
    collector_schedule_extra_run_attempts: int = Field(
        default=1,
        ge=0,
        le=5,
        description=(
            "If a scheduled collector run fails with a transient-ish error "
            "before opening an ingestion run, retry the full pipeline once (value=1)."
        ),
    )
    collector_schedule_retry_backoff_seconds: float = Field(
        default=35.0,
        ge=0.0,
        le=900.0,
        description="Base delay multiplied by attempt index between full pipeline retries.",
    )
    collector_schedule_error_retry_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=86_400.0,
        description=(
            "After a failed collector schedule run, if the error looks transient and "
            "no ingestion_run_id was opened, set next_run_at to min(normal next, now + this). "
            "0 = cadence only (parity with ATLAS_DELIVERY_SCHEDULE_ERROR_RETRY_SECONDS)."
        ),
    )

    # --- Sprint I.2: time-decayed learning (learn_from_feedback) ----------------
    learning_feedback_decay_half_life_days: float = Field(
        default=0.0,
        ge=0.0,
        le=730.0,
        description=(
            "When >0, learn_from_feedback uses exponentially decaying weights "
            "(0.5^(age_days/half_life)) per labeled job from its feedback anchor "
            "time. 0 = uniform weighting (legacy behavior)."
        ),
    )

    ranker_text_signals_max_vector_terms: int = Field(
        default=400,
        ge=50,
        le=3000,
        description="Trim profile TF–IDF reference vectors to this many top terms.",
    )
    ranker_synergy_profile_fit_boost: float = Field(
        default=0.0,
        ge=0.0,
        le=8.0,
        description=(
            "When >0, add this many ranking points when web3_fit and description_fit "
            "both exceed ~60% of their caps (after base normalization)."
        ),
    )

    # --- Digest “top jobs” alert (optional, W5 post-build ping) -------------
    digest_alert_enabled: bool = Field(
        default=False,
        description=(
            "When true, evaluate each persisted digest immediately after build; "
            "if any item has ranking_score >= digest_alert_min_ranking_score within "
            "the top digest_alert_top_jobs slice, optionally POST digest_alert_webhook_url "
            "and/or email digest_alert_email_to (SMTP same as deliveries)."
        ),
    )
    digest_alert_min_ranking_score: float = Field(
        default=75.0,
        ge=0.0,
        le=100.0,
        description="Minimum ranking_score on a digest item to count toward alerts.",
    )
    digest_alert_webhook_url: str | None = Field(
        default=None,
        description="HTTPS URL (e.g. Slack incoming webhook); receives JSON with text+digest meta.",
    )
    digest_alert_email_to: str | None = Field(
        default=None,
        description=(
            "Comma/semicolon separated addresses for a short plaintext alert "
            "(requires ATLAS_SMTP_* like digest deliveries)."
        ),
    )
    digest_alert_top_jobs: int = Field(
        default=8,
        ge=1,
        le=40,
        description="Max digest lines to enumerate in the alert (sorted by ranking_score desc).",
    )

    # --- Per-company ATS sources CSV ----------------------------------------
    company_sources_csv: str | None = Field(
        default=None,
        description=(
            "Path to a SourceRow-format CSV of per-company ATS boards "
            "(e.g. scripts/company_ats_sources.csv). Relative paths are "
            "resolved from ATLAS_REPO_ROOT. Leave unset to skip."
        ),
    )

    # --- RemoteOK aggregator collector (app/collectors/remoteok.py) -----------
    remoteok_enabled: bool = Field(
        default=True,
        description="Enable the RemoteOK JSON API aggregator in the collector pipeline.",
    )
    remoteok_tags: str = Field(
        default="community,marketing,growth,content,social-media,seo,customer-success,customer-support,operations,product-management,partnerships,devrel,communications,brand",
        description="Comma-separated RemoteOK tags to include. Empty = all jobs.",
    )
    remoteok_max_jobs: int = Field(
        default=300,
        ge=1,
        le=2000,
        description="Max jobs to pull per RemoteOK collection run.",
    )
    remoteok_max_age_days: int = Field(
        default=14,
        ge=1,
        le=90,
        description="Skip RemoteOK jobs older than this many days.",
    )

    # --- We Work Remotely RSS collector (app/collectors/weworkremotely.py) ---
    wwr_enabled: bool = Field(
        default=True,
        description="Enable the We Work Remotely RSS aggregator in the collector pipeline.",
    )
    wwr_categories: str = Field(
        default="marketing,customer-support,management-and-finance,all-other",
        description="Comma-separated WWR category slugs (e.g. marketing, customer-support).",
    )
    wwr_max_jobs: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Max total jobs to pull from WWR RSS feeds per run.",
    )
    wwr_max_age_days: int = Field(
        default=14,
        ge=1,
        le=90,
        description="Skip WWR jobs older than this many days.",
    )

    # --- Arbeitnow aggregator ------------------------------------------------
    arbeitnow_enabled: bool = Field(
        default=True,
        description="Enable the Arbeitnow free jobs API aggregator collector.",
    )
    arbeitnow_max_jobs: int = Field(
        default=200,
        ge=1,
        le=2000,
        description="Maximum Arbeitnow jobs to collect per run.",
    )
    arbeitnow_max_age_days: int = Field(
        default=14,
        ge=1,
        le=90,
        description="Skip Arbeitnow jobs older than this many days.",
    )
    arbeitnow_page_gap_seconds: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
        description="Polite delay between Arbeitnow pagination requests.",
    )

    # --- Workday ATS ---------------------------------------------------------
    workday_page_pause_seconds: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
        description="Polite delay between Workday pagination requests.",
    )

    # --- JSearch (RapidAPI) --------------------------------------------------
    # Free: 200 req/month. Basic: ~$10/mo for 3k. Pro: ~$50/mo for 30k.
    # Upgrade = change your RapidAPI plan + bump jsearch_max_jobs. No code change.
    jsearch_api_key: str | None = Field(
        default=None,
        description="RapidAPI key for JSearch. Get at rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch",
    )
    jsearch_enabled: bool = Field(
        default=False,
        description="Enable JSearch aggregator (requires jsearch_api_key).",
    )
    jsearch_max_jobs: int = Field(
        default=200,
        ge=1,
        le=5000,
        description=(
            "Max jobs per JSearch run. Free tier: stay ≤200. "
            "Basic (~$10/mo): up to 1000. Pro (~$50/mo): up to 5000."
        ),
    )
    jsearch_max_pages: int = Field(
        default=2,
        ge=1,
        le=20,
        description="Max pages per query in JSearch (10 jobs/page by default).",
    )
    jsearch_page_gap_seconds: float = Field(
        default=0.8,
        ge=0.0,
        le=10.0,
        description="Polite delay between JSearch page requests.",
    )
    jsearch_employment_types: str = Field(
        default="FULLTIME,CONTRACTOR",
        description="Comma-separated JSearch employment types filter.",
    )
    jsearch_date_posted: str = Field(
        default="week",
        description="JSearch date_posted filter: today, 3days, week, month.",
    )
    jsearch_queries: str | None = Field(
        default=None,
        description="Pipe-separated search queries for JSearch. Defaults to built-in community/marketing list.",
    )

    # --- Adzuna ---------------------------------------------------------------
    # Free: 250 calls/day. Paid: unlimited at ~$0.001/call.
    # Upgrade = email Adzuna to lift daily cap. No code change.
    adzuna_app_id: str | None = Field(
        default=None,
        description="Adzuna API app_id. Sign up at developer.adzuna.com.",
    )
    adzuna_app_key: str | None = Field(
        default=None,
        description="Adzuna API app_key. Sign up at developer.adzuna.com.",
    )
    adzuna_enabled: bool = Field(
        default=False,
        description="Enable Adzuna aggregator (requires adzuna_app_id and adzuna_app_key).",
    )
    adzuna_max_jobs: int = Field(
        default=200,
        ge=1,
        le=5000,
        description=(
            "Max jobs per Adzuna run. Free tier: ≤250 calls/day total. "
            "Paid: no limit — raise freely."
        ),
    )
    adzuna_max_pages: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Max pages per Adzuna query (up to 50 results/page).",
    )
    adzuna_results_per_page: int = Field(
        default=50,
        ge=1,
        le=50,
        description="Results per Adzuna page (max 50).",
    )
    adzuna_page_gap_seconds: float = Field(
        default=0.6,
        ge=0.0,
        le=10.0,
        description="Polite delay between Adzuna pagination requests.",
    )
    adzuna_max_days_old: int = Field(
        default=14,
        ge=1,
        le=90,
        description="Skip Adzuna jobs older than this many days.",
    )
    adzuna_countries: str = Field(
        default="us",
        description=(
            "Comma-separated ISO2 country codes for Adzuna. "
            "Available: us,gb,ca,au,de,fr,nl,sg,nz,at,be,br,in,it,mx,pl,ru,za. "
            "Add gb,ca for broader remote coverage."
        ),
    )
    adzuna_query: str | None = Field(
        default=None,
        description="Override Adzuna search query. Defaults to built-in community/marketing query.",
    )

    # --- The Muse job board --------------------------------------------------
    themuse_enabled: bool = Field(
        default=True,
        description="Enable The Muse job board collector.",
    )
    themuse_api_key: str | None = Field(
        default=None,
        description=(
            "Optional The Muse API key. Without it you get 500 req/hr; "
            "with it 3600 req/hr. Register at themuse.com/developers."
        ),
    )
    themuse_max_jobs: int = Field(
        default=200,
        ge=1,
        le=2000,
        description="Max jobs to collect per The Muse run.",
    )
    themuse_max_pages_per_category: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Max pages to fetch per category (20 jobs/page).",
    )
    themuse_page_gap_seconds: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
        description="Polite delay between The Muse page requests.",
    )

    # --- Jobicy aggregator (collectors/jobicy.py) ----------------------------
    jobicy_enabled: bool = Field(
        default=True,
        description="Enable the Jobicy remote jobs aggregator collector.",
    )
    jobicy_max_jobs: int = Field(
        default=200,
        ge=1,
        le=2000,
        description="Max jobs to collect per Jobicy run.",
    )
    jobicy_max_age_days: int = Field(
        default=14,
        ge=1,
        le=90,
        description="Reject Jobicy jobs older than this many days.",
    )
    jobicy_count_per_call: int = Field(
        default=50,
        ge=1,
        le=50,
        description="Jobs per Jobicy API call (max 50 per their docs).",
    )

    # --- Himalayas aggregator (collectors/himalayas.py) ----------------------
    himalayas_enabled: bool = Field(
        default=True,
        description="Enable the Himalayas remote jobs aggregator collector.",
    )
    jobstash_enabled: bool = Field(
        default=True,
        description="Enable the Jobstash web3 job aggregator collector.",
    )
    himalayas_max_jobs: int = Field(
        default=300,
        ge=1,
        le=2000,
        description="Max jobs to collect per Himalayas run.",
    )
    himalayas_max_age_days: int = Field(
        default=14,
        ge=1,
        le=90,
        description="Reject Himalayas jobs older than this many days.",
    )
    himalayas_max_pages_per_query: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Max pages to fetch per Himalayas search query.",
    )
    himalayas_page_gap_seconds: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
        description="Polite delay between Himalayas page requests.",
    )

    # --- ATS board discovery -------------------------------------------------
    serpapi_key: str | None = Field(
        default=None,
        description=(
            "Optional SerpAPI key for ATS board discovery. "
            "When set, discover_ats_boards.py uses the Google search API. "
            "Falls back to DuckDuckGo HTML scraping when absent."
        ),
    )

    # --- 1-click find-jobs endpoint defaults --------------------------------
    find_jobs_then_digest: bool = Field(
        default=True,
        description="Auto-generate a digest after collection in the /pipeline/find-jobs endpoint.",
    )
    find_jobs_digest_fresh_hours: int = Field(
        default=72,
        ge=1,
        le=720,
        description="Fresh-window hours for the digest generated by /pipeline/find-jobs.",
    )

    def assert_postgres(self) -> None:
        if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")):
            raise RuntimeError(
                "ATLAS_DATABASE_URL must point to PostgreSQL. SQLite is not supported."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.assert_postgres()
    return s
