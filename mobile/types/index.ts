// ── Jobs ─────────────────────────────────────────────────────────────────────

export interface Job {
  id: number
  title: string
  company: string
  location: string | null
  remote_type: string | null
  canonical_apply_url: string
  description: string | null
  quality_score: number | null
  ranking_score: number | null
  source_count: number
  created_at: string
  updated_at: string
}

// ── Digests ───────────────────────────────────────────────────────────────────

export type DigestType = 'daily' | 'weekly' | 'hidden_gems' | 'custom'

/** Returned by GET /digests list endpoint */
export interface DigestSummary {
  id: string
  generated_at: string
  digest_type: DigestType
  notes: string | null
  item_count: number
}

/** Backward-compatible alias */
export type Digest = DigestSummary

/** A single job entry inside a digest lane */
export interface DigestLaneItem {
  job: Job
  lane: string
  reason: string | null
  rank_position: number
}

/** Legacy alias — only job/rank_position fields guaranteed */
export type DigestItem = DigestLaneItem

export interface DigestStats {
  fresh_selected: number
  gem_selected: number
  fresh_candidates: number
  gem_candidates: number
  dropped_by_cap: number
  excluded_by_feedback: number
  excluded_by_qualification: number
}

/** Returned by GET /digests/{id} and POST /digests/generate */
export interface DigestDetail extends DigestSummary {
  fresh: DigestLaneItem[]
  hidden_gems: DigestLaneItem[]
  stats: DigestStats | null
}

/** POST /digests/generate request body */
export interface DigestGenerateRequest {
  digest_type?: DigestType
  fresh_hours?: number
  fresh_limit?: number
  gem_limit?: number
  per_company_cap?: number
  min_ranking_score?: number
  gem_min_score?: number
  notes?: string | null
  profile_slug?: string | null
  apply_qualification?: boolean
}

// ── Schedules ─────────────────────────────────────────────────────────────────

export type ScheduleCadence = 'daily' | 'hourly' | 'every_n_minutes' | 'cron'
export type ScheduleChannel = 'slack' | 'email' | 'csv_only' | 'none'

export interface Schedule {
  id: string
  name: string
  cadence: ScheduleCadence
  hour_utc: number | null
  minute_utc: number | null
  interval_minutes: number | null
  cron_expression: string | null
  profile_slug: string | null
  digest_config: Record<string, unknown>
  channel: ScheduleChannel
  webhook_url: string | null
  recipients: string[]
  include_hidden_gems: boolean
  is_active: boolean
  last_run_at: string | null
  next_run_at: string | null
  last_status: string | null
  last_error: string | null
  last_digest_id: string | null
  created_at: string
  updated_at: string
}

export interface ScheduleCreate {
  name: string
  cadence: ScheduleCadence
  hour_utc?: number | null
  minute_utc?: number | null
  interval_minutes?: number | null
  cron_expression?: string | null
  channel: ScheduleChannel
  webhook_url?: string | null
  recipients?: string[]
  include_hidden_gems?: boolean
  profile_slug?: string | null
  digest_config?: Record<string, unknown>
  is_active?: boolean
}

export interface ScheduleRunResult {
  schedule_id: string
  status: 'ok' | 'error' | 'skipped'
  digest_id: string | null
  channel: string
  delivered: boolean
  detail: string | null
  duration_ms: number
}

// ── Qualification ─────────────────────────────────────────────────────────────

export interface QualificationRules {
  min_ranking_score?: number | null
  remote_types_allowed?: string[] | null
  title_or_description_must_contain_any?: string[] | null
  block_if_text_contains_any?: string[] | null
  company_name_block_substrings?: string[] | null
}

// ── Applications ──────────────────────────────────────────────────────────────

export interface ApplicationJobTrack {
  id: string
  canonical_job_id: string
  current_stage: string
  notes: string | null
  created_at: string
  updated_at: string
  stage_changed_at: string | null
  application_outcome: string | null
  job_title: string | null
  job_company_name: string | null
  job_apply_url: string | null
}

export interface ApplicationPackage {
  id: number
  job_id: number
  version: number
  resume_markdown: string | null
  cover_letter_markdown: string | null
  strategy_notes: string | null
  created_at: string
}

// ── Career Memory ─────────────────────────────────────────────────────────────

export interface CareerDocument {
  id: number
  name: string
  content_type: string | null
  ingested_at: string | null
  preview: string | null
}

export interface CareerFact {
  id: number
  source_document_id: number | null
  fact_text: string
  fact_type: string
  verification_state: string   // "draft" | "approved" | "rejected"
  confidence_score: number
  source_trace: string | null
  is_core_proof_point: number  // 0 | 1
  text_edited_at: string | null
}

export interface TimelineEntry {
  id: number
  source_document_id: number | null
  title: string
  company: string | null
  start_date: string | null
  end_date: string | null
  summary: string | null
  status: string
  confidence_score: number
  created_at: string | null
}

export interface ProfileQuestion {
  id: number
  canonical_job_id: string | null
  job_title: string | null
  job_company: string | null
  question_text: string
  question_type: string
  status: string   // "open" | "answered" | "dismissed"
  priority: string
}

export interface CareerMemorySummary {
  facts_total: number
  facts_draft: number
  facts_approved: number
  facts_rejected: number
  core_proof_points: number
  questions_open: number
  questions_answered: number
  questions_dismissed: number
  underused_fact_types: string[]
}

// ── Feedback ──────────────────────────────────────────────────────────────────

export interface FeedbackEvent {
  id: string
  job_id: string
  profile_id: string | null
  profile_slug: string | null
  action: string
  source: string
  note: string | null
  created_at: string
}

export interface FeedbackListResponse {
  total: number
  items: FeedbackEvent[]
}

// ── Pipeline Stats ────────────────────────────────────────────────────────────

export interface JobBuckets {
  total: number
  top: number
  strong: number
  maybe: number
  skip: number
}

export interface PipelineStats {
  jobs_active: JobBuckets
  pending_raw_events: number
  needs_review: number
  latest_run: {
    id: string
    source_name: string
    source_type: string
    started_at: string
    completed_at: string | null
    status: string
    rows_seen: number
    rows_inserted: number
    rows_failed: number
  } | null
  latest_digest: {
    id: string
    generated_at: string
    digest_type: string
    item_count: number
  } | null
}

export interface FindJobsResult {
  ok: boolean
  new_jobs: number
  duration_sec: number
  digest_id: string | null
  error: string | null
}

// ── Profiles & Scoring ────────────────────────────────────────────────────────

export interface Profile {
  id: number
  slug: string
  display_name: string
  description: string | null
  weights: Record<string, number>
  remote_bias: string | null
  strong_keywords: string[]
  weak_keywords: string[]
  negative_keywords: string[]
}

export interface DashboardLane {
  stage: string
  count: number
  tracks: ApplicationJobTrack[]
}

// ── Collector Schedules ───────────────────────────────────────────────────────

export interface CollectorSchedule {
  id: string
  name: string
  cadence: ScheduleCadence
  hour_utc: number | null
  minute_utc: number | null
  interval_minutes: number | null
  cron_expression: string | null
  then_import: boolean
  then_rank: boolean
  then_digest: boolean
  is_active: boolean
  last_run_at: string | null
  next_run_at: string | null
  last_status: string | null
  created_at: string
}

export interface CollectorScheduleCreate {
  name: string
  cadence: ScheduleCadence
  hour_utc?: number | null
  minute_utc?: number | null
  interval_minutes?: number | null
  cron_expression?: string | null
  then_import?: boolean
  then_rank?: boolean
  then_digest?: boolean
  is_active?: boolean
}

// ── Candidate Profile ─────────────────────────────────────────────────────────

export interface CandidateProfile {
  id: string
  user_id: string
  full_name: string | null
  email: string | null
  phone: string | null
  location: string | null
  linkedin_url: string | null
  website_url: string | null
  headline: string | null
  summary: string | null
  home_city: string | null
  home_lat: number | null
  home_lng: number | null
  search_radius_km: number
  target_cities: string[] | null
  search_mode: string
  created_at: string
  updated_at: string
}

export type SearchMode = 'remote' | 'local' | 'both' | 'target' | 'all'

export interface CandidateProfileUpdate {
  full_name?: string | null
  email?: string | null
  phone?: string | null
  location?: string | null
  linkedin_url?: string | null
  website_url?: string | null
  headline?: string | null
  summary?: string | null
  home_city?: string | null
  home_lat?: number | null
  home_lng?: number | null
  search_radius_km?: number
  target_cities?: string[] | null
  search_mode?: SearchMode
}

// ── Misc ──────────────────────────────────────────────────────────────────────

export type JobReaction = 'saved' | 'applied' | 'dismissed' | 'interviewed' | 'rejected' | 'clicked'
