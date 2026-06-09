import { useConfigStore } from '../stores/config'
import type {
  Job,
  DigestSummary,
  DigestDetail,
  DigestGenerateRequest,
  ApplicationJobTrack,
  ApplicationPackage,
  CareerFact,
  CareerDocument,
  ProfileQuestion,
  TimelineEntry,
  CareerMemorySummary,
  FeedbackListResponse,
  FindJobsResult,
  PipelineStats,
  Profile,
  DashboardLane,
  Schedule,
  ScheduleCreate,
  ScheduleRunResult,
  QualificationRules,
  CollectorSchedule,
  CollectorScheduleCreate,
  CandidateProfile,
  CandidateProfileUpdate,
} from '../types'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { apiBase, adminToken } = useConfigStore.getState()
  const res = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(adminToken ? { 'X-Admin-Token': adminToken } : {}),
      ...options?.headers,
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${text}`)
  }
  if (res.status === 204 || res.headers.get('content-length') === '0') {
    return undefined as unknown as T
  }
  return res.json()
}

function buildQs(params: Record<string, string | number | boolean | undefined | null>): string {
  const entries = Object.entries(params)
    .filter(([, v]) => v != null)
    .map(([k, v]) => [k, String(v)] as [string, string])
  return entries.length ? '?' + new URLSearchParams(entries).toString() : ''
}

export const api = {
  // ── Connectivity ────────────────────────────────────────────────────────────

  ping: async (): Promise<boolean> => {
    try {
      await request<unknown>('/jobs?limit=1')
      return true
    } catch {
      return false
    }
  },

  // ── Jobs ────────────────────────────────────────────────────────────────────

  getJobs: async (params?: {
    profile_slug?: string
    limit?: number
    offset?: number
    q?: string
    remote_type?: string
    min_score?: number
    order?: 'last_seen' | 'first_seen' | 'ranking' | 'quality'
    first_seen_after?: string
  }): Promise<Job[]> => {
    const res = await request<{ total: number; limit: number; offset: number; items: Array<Record<string, unknown>> }>(
      `/jobs${buildQs(params ?? {})}`
    )
    const items = Array.isArray(res) ? res : (res.items ?? [])
    // Normalise backend field names to mobile Job shape
    return items.map((j) => ({
      ...j,
      company: (j.company ?? j.company_name) as string,
      description: (j.description ?? j.description_clean ?? null) as string | null,
    })) as unknown as Job[]
  },

  getJob: async (id: string): Promise<Job> => {
    const j = await request<Record<string, unknown>>(`/jobs/${id}`)
    return {
      ...j,
      company: (j.company ?? j.company_name) as string,
      description: (j.description ?? j.description_clean ?? null) as string | null,
    } as unknown as Job
  },

  submitFeedback: (jobId: string, action: string, profileSlug?: string) =>
    request<void>(`/jobs/${jobId}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ action, profile_slug: profileSlug ?? null, source: 'ui' }),
    }),

  // ── Digests ─────────────────────────────────────────────────────────────────

  /** Returns the list of digest summaries (unwrapped from paginated envelope). */
  getDigests: async (params?: { limit?: number; offset?: number }): Promise<DigestSummary[]> => {
    const result = await request<{ total: number; limit: number; offset: number; items: DigestSummary[] }>(
      `/digests${buildQs(params ?? {})}`
    )
    // Handle both paginated envelope and legacy plain array
    return Array.isArray(result) ? result : (result.items ?? [])
  },

  getDigest: (id: string) => request<DigestDetail>(`/digests/${id}`),

  generateDigest: (params?: DigestGenerateRequest) =>
    request<DigestDetail>('/digests/generate', {
      method: 'POST',
      body: JSON.stringify(params ?? {}),
    }),

  // ── Pipeline / Applications ─────────────────────────────────────────────────

  getDashboard: (profileId?: number) =>
    request<DashboardLane[]>(`/applications/dashboard${buildQs({ profile_id: profileId })}`),

  getJobTracks: () => request<{ total: number; items: ApplicationJobTrack[] }>('/applications/job-tracks').then(r => r.items),

  addJobTrack: (canonicalJobId: string, stage: string = 'saved') =>
    request<ApplicationJobTrack>('/applications/job-tracks', {
      method: 'POST',
      body: JSON.stringify({ canonical_job_id: canonicalJobId, current_stage: stage }),
    }),

  updateTrackStage: (trackId: string, stage: string) =>
    request<ApplicationJobTrack>(`/applications/job-tracks/${trackId}`, {
      method: 'PATCH',
      body: JSON.stringify({ current_stage: stage }),
    }),

  deleteTrack: (trackId: string) =>
    request<void>(`/applications/job-tracks/${trackId}`, { method: 'DELETE' }),

  /** Accepts URL or raw JD text */
  intakeJob: (payload: { url?: string; text?: string }) =>
    request<{ job_id: number }>('/applications/jobs/intake', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // ── Application Packages ────────────────────────────────────────────────────

  getPackages: (jobId: string) =>
    request<{ total: number; items: ApplicationPackage[] }>(`/applications/jobs/${jobId}/packages`).then(r => r.items),

  generatePackage: (jobId: string) =>
    request<ApplicationPackage>(`/applications/jobs/${jobId}/packages/generate`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  // ── Career Memory — Documents ───────────────────────────────────────────────

  getDocuments: () => request<CareerDocument[]>('/career-memory/documents'),

  deleteDocument: (documentId: number) =>
    request<void>(`/career-memory/documents/${documentId}`, { method: 'DELETE' }),

  reExtractFacts: (documentId: number) =>
    request<{ ok: boolean; new_facts: number }>(`/career-memory/documents/${documentId}/re-extract`, { method: 'POST' }),

  uploadDocument: async (fileUri: string, filename: string, mimeType: string): Promise<CareerDocument> => {
    const { apiBase, adminToken } = useConfigStore.getState()
    const formData = new FormData()
    formData.append('file', {
      uri: fileUri,
      name: filename,
      type: mimeType,
    } as unknown as Blob)

    const res = await fetch(`${apiBase}/career-memory/documents`, {
      method: 'POST',
      headers: {
        ...(adminToken ? { 'X-Admin-Token': adminToken } : {}),
      },
      body: formData,
    })
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText)
      throw new Error(`${res.status}: ${text}`)
    }
    return res.json()
  },

  // ── Career Memory — Facts ───────────────────────────────────────────────────

  getCareerFacts: (params?: { fact_type?: string; limit?: number }) =>
    request<CareerFact[]>(`/career-memory/facts${buildQs(params ?? {})}`),

  updateFact: (factId: number, patch: { verification_state?: string; is_core_proof_point?: number; fact_text?: string }) =>
    request<CareerFact>(`/career-memory/facts/${factId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  deleteFact: (factId: number) =>
    request<{ ok: boolean }>(`/career-memory/facts/${factId}`, { method: 'DELETE' }),

  // ── Career Memory — Questions ───────────────────────────────────────────────

  getQuestions: () => request<ProfileQuestion[]>('/career-memory/questions'),

  generateQuestions: () =>
    request<ProfileQuestion[]>('/career-memory/questions/generate', { method: 'POST' }),

  answerQuestion: (questionId: number, answerText: string) =>
    request<{ ok: boolean; question_id: number; created_fact_id: number }>(
      `/career-memory/questions/${questionId}/answer`,
      { method: 'POST', body: JSON.stringify({ answer_text: answerText }) }
    ),

  dismissQuestion: (questionId: number) =>
    request<{ ok: boolean; question_id: number; status: string }>(
      `/career-memory/questions/${questionId}/status`,
      { method: 'PATCH', body: JSON.stringify({ status: 'dismissed' }) }
    ),

  deleteQuestion: (questionId: number) =>
    request<void>(`/career-memory/questions/${questionId}`, { method: 'DELETE' }),

  // ── Career Memory — Timeline & Summary ─────────────────────────────────────

  getTimeline: () => request<TimelineEntry[]>('/career-memory/timeline'),

  getMemorySummary: () => request<CareerMemorySummary>('/career-memory/summary'),

  // ── Feedback ────────────────────────────────────────────────────────────────

  getFeedback: (params?: { limit?: number; offset?: number; action?: string }) =>
    request<FeedbackListResponse>(`/feedback${buildQs(params ?? {})}`),

  // ── Find Jobs (1-click collect → import → rank → digest) ────────────────────

  findJobs: () =>
    request<FindJobsResult>('/pipeline/find-jobs', { method: 'POST' }),

  cancelPipeline: () =>
    request<{ ok: boolean; message: string }>('/pipeline/cancel', { method: 'POST' }),

  // ── Pipeline Stats ───────────────────────────────────────────────────────────

  getPipelineStats: () => request<PipelineStats>('/pipeline/stats'),

  // ── Profiles ────────────────────────────────────────────────────────────────

  getProfiles: () => request<{ total: number; items: Profile[] }>('/profiles').then(r => r.items),

  getTemplates: () =>
    request<{ templates: { slug: string; display_name: string; description: string }[] }>(
      '/profiles/templates'
    ).then(r => r.templates),

  createProfileFromTemplate: (templateSlug: string, preferredRemote?: 'remote' | 'hybrid' | 'onsite') =>
    request<Profile>('/profiles/from-template', {
      method: 'POST',
      body: JSON.stringify({ template_slug: templateSlug, preferred_remote: preferredRemote ?? null }),
    }),

  // ── Schedules ───────────────────────────────────────────────────────────────

  getSchedules: async (params?: { only_active?: boolean }): Promise<Schedule[]> => {
    const result = await request<{ total: number; items: Schedule[] }>(
      `/schedules${buildQs(params ?? {})}`
    )
    return Array.isArray(result) ? result : (result.items ?? [])
  },

  createSchedule: (data: ScheduleCreate) =>
    request<Schedule>('/schedules', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateSchedule: (id: string, data: Partial<ScheduleCreate>) =>
    request<Schedule>(`/schedules/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  deleteSchedule: (id: string) =>
    request<void>(`/schedules/${id}`, { method: 'DELETE' }),

  runScheduleNow: (id: string) =>
    request<ScheduleRunResult>(`/schedules/${id}/run-now`, { method: 'POST' }),

  // ── Collector Schedules ──────────────────────────────────────────────────────

  getCollectorSchedules: async (): Promise<CollectorSchedule[]> => {
    const result = await request<{ total: number; items: CollectorSchedule[] } | CollectorSchedule[]>(
      '/collector-schedules'
    )
    return Array.isArray(result) ? result : (result.items ?? [])
  },

  createCollectorSchedule: (data: CollectorScheduleCreate) =>
    request<CollectorSchedule>('/collector-schedules', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateCollectorSchedule: (id: string, data: Partial<CollectorScheduleCreate>) =>
    request<CollectorSchedule>(`/collector-schedules/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  deleteCollectorSchedule: (id: string) =>
    request<void>(`/collector-schedules/${id}`, { method: 'DELETE' }),

  // ── Qualification Rules ──────────────────────────────────────────────────────

  getQualificationRules: () =>
    request<{ rules: QualificationRules }>('/qualification/settings'),

  updateQualificationRules: (rules: QualificationRules) =>
    request<{ rules: QualificationRules }>('/qualification/settings', {
      method: 'PUT',
      body: JSON.stringify({ rules }),
    }),

  // ── Candidate Profile ────────────────────────────────────────────────────────

  getCandidateProfile: () =>
    request<CandidateProfile | null>('/candidate-profile'),

  upsertCandidateProfile: (data: CandidateProfileUpdate) =>
    request<CandidateProfile>('/candidate-profile', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // ── Collection Status ────────────────────────────────────────────────────────

  getCollectionStatus: () =>
    request<{
      last_collected_at: string | null
      next_run_at: string | null
      total_active_jobs: number
      boards_collected_24h: number
      boards_fresh: number
      boards_blocklisted: number
      boards_total: number
      status: string
    }>('/collection/status'),

  // ── Rescore ──────────────────────────────────────────────────────────────────

  rescoreJobs: (opts: { onlyUnscored?: boolean } = {}) =>
    request<{ scored: number; failed: number; hidden_gems: number; by_bucket: Record<string, number> }>(
      '/imports/rescore',
      {
        method: 'POST',
        body: JSON.stringify({ only_active: true, only_unscored: opts.onlyUnscored ?? false }),
      }
    ),
}
