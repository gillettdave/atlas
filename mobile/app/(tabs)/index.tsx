import {
  View,
  Text,
  FlatList,
  SectionList,
  Pressable,
  RefreshControl,
  ActivityIndicator,
  Modal,
  TextInput,
  KeyboardAvoidingView,
  ScrollView,
  Switch,
  Platform,
  Alert,
  AppState,
} from 'react-native'
import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../services/api'
import { JobCard } from '../../components/JobCard'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { useConfigStore } from '../../stores/config'
import type { FeedLocationMode } from '../../stores/config'
import type { DigestLaneItem, DigestGenerateRequest, DigestType, Job, Profile, CandidateProfile } from '../../types'

type FeedMode = 'digest' | 'browse'
type IntakeMode = 'url' | 'text'

const BROWSE_LIMIT = 30

const DIGEST_TYPES: { value: DigestType; label: string }[] = [
  { value: 'daily',       label: 'Daily' },
  { value: 'weekly',      label: 'Weekly' },
  { value: 'hidden_gems', label: 'Gems' },
  { value: 'custom',      label: 'Custom' },
]

// ── Stepper ───────────────────────────────────────────────────────────────────

function Stepper({
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  value: number
  min: number
  max: number
  step?: number
  onChange: (v: number) => void
}) {
  return (
    <View className="flex-row items-center gap-2">
      <Pressable
        className="w-8 h-8 bg-gray-800 rounded-lg items-center justify-center active:opacity-75"
        onPress={() => onChange(Math.max(min, value - step))}
      >
        <Text className="text-gray-300 font-bold text-base leading-none">−</Text>
      </Pressable>
      <Text className="text-gray-100 font-semibold text-sm w-10 text-center">{value}</Text>
      <Pressable
        className="w-8 h-8 bg-gray-800 rounded-lg items-center justify-center active:opacity-75"
        onPress={() => onChange(Math.min(max, value + step))}
      >
        <Text className="text-gray-300 font-bold text-base leading-none">+</Text>
      </Pressable>
    </View>
  )
}

// ── Digest Options Modal ──────────────────────────────────────────────────────

const DEFAULT_OPTS: Required<Omit<DigestGenerateRequest, 'notes' | 'profile_slug'>> = {
  digest_type:         'daily',
  fresh_hours:         48,
  fresh_limit:         15,
  gem_limit:           10,
  per_company_cap:     3,
  min_ranking_score:   35,
  gem_min_score:       60,
  apply_qualification: true,
}

function DigestOptionsModal({
  visible,
  onClose,
  onGenerate,
  generating,
  profiles,
}: {
  visible: boolean
  onClose: () => void
  onGenerate: (opts: DigestGenerateRequest) => void
  generating: boolean
  profiles: Profile[]
}) {
  const { activeProfileSlug } = useConfigStore()
  const [opts, setOpts] = useState<DigestGenerateRequest>({
    ...DEFAULT_OPTS,
    profile_slug: activeProfileSlug,
  })

  function set<K extends keyof DigestGenerateRequest>(key: K, val: DigestGenerateRequest[K]) {
    setOpts((prev) => ({ ...prev, [key]: val }))
  }

  function Row({ label, children }: { label: string; children: React.ReactNode }) {
    return (
      <View className="flex-row items-center justify-between px-4 py-3 border-b border-gray-800">
        <Text className="text-gray-300 text-sm flex-1 mr-4">{label}</Text>
        {children}
      </View>
    )
  }

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
      onShow={() => setOpts({ ...DEFAULT_OPTS, profile_slug: activeProfileSlug })}
    >
      <View className="flex-1 bg-gray-950">
        {/* Header */}
        <View className="flex-row items-center justify-between px-5 pt-5 pb-3 border-b border-gray-800">
          <Pressable onPress={onClose} className="active:opacity-75">
            <Text className="text-gray-400 text-base">Cancel</Text>
          </Pressable>
          <Text className="text-gray-100 font-semibold text-base">Digest Options</Text>
          <Pressable
            onPress={() => onGenerate(opts)}
            disabled={generating}
            className="active:opacity-75"
          >
            {generating ? (
              <ActivityIndicator size="small" color="#818cf8" />
            ) : (
              <Text className="text-indigo-400 font-semibold text-base">Generate</Text>
            )}
          </Pressable>
        </View>

        <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
          {/* Digest type */}
          <Text className="text-gray-500 text-xs uppercase font-semibold tracking-widest px-5 pt-5 pb-2">
            Digest Type
          </Text>
          <View className="flex-row bg-gray-900 rounded-xl mx-5 p-0.5 border border-gray-800">
            {DIGEST_TYPES.map((dt) => (
              <Pressable
                key={dt.value}
                className={`flex-1 py-2 rounded-lg items-center active:opacity-75 ${
                  opts.digest_type === dt.value ? 'bg-gray-700' : ''
                }`}
                onPress={() => set('digest_type', dt.value)}
              >
                <Text
                  className={`text-xs font-medium ${
                    opts.digest_type === dt.value ? 'text-gray-100' : 'text-gray-500'
                  }`}
                  numberOfLines={1}
                >
                  {dt.label}
                </Text>
              </Pressable>
            ))}
          </View>

          {/* Scoring */}
          <Text className="text-gray-500 text-xs uppercase font-semibold tracking-widest px-5 pt-5 pb-2">
            Score Thresholds
          </Text>
          <View className="bg-gray-900 rounded-xl mx-5 border border-gray-800 overflow-hidden">
            <Row label={`Min ranking score  ${opts.min_ranking_score}`}>
              <Stepper
                value={opts.min_ranking_score ?? 35}
                min={0} max={100} step={5}
                onChange={(v) => set('min_ranking_score', v)}
              />
            </Row>
            <Row label={`Hidden gem min score  ${opts.gem_min_score}`}>
              <Stepper
                value={opts.gem_min_score ?? 60}
                min={0} max={100} step={5}
                onChange={(v) => set('gem_min_score', v)}
              />
            </Row>
          </View>

          {/* Limits */}
          <Text className="text-gray-500 text-xs uppercase font-semibold tracking-widest px-5 pt-5 pb-2">
            Result Limits
          </Text>
          <View className="bg-gray-900 rounded-xl mx-5 border border-gray-800 overflow-hidden">
            <Row label={`Fresh jobs  ${opts.fresh_limit}`}>
              <Stepper
                value={opts.fresh_limit ?? 15}
                min={0} max={50} step={5}
                onChange={(v) => set('fresh_limit', v)}
              />
            </Row>
            <Row label={`Hidden gems  ${opts.gem_limit}`}>
              <Stepper
                value={opts.gem_limit ?? 10}
                min={0} max={30} step={5}
                onChange={(v) => set('gem_limit', v)}
              />
            </Row>
            <Row label={`Per-company cap  ${opts.per_company_cap}`}>
              <Stepper
                value={opts.per_company_cap ?? 3}
                min={1} max={20}
                onChange={(v) => set('per_company_cap', v)}
              />
            </Row>
            <Row label={`Freshness window  ${opts.fresh_hours}h`}>
              <Stepper
                value={opts.fresh_hours ?? 48}
                min={1} max={168} step={12}
                onChange={(v) => set('fresh_hours', v)}
              />
            </Row>
          </View>

          {/* Options */}
          <Text className="text-gray-500 text-xs uppercase font-semibold tracking-widest px-5 pt-5 pb-2">
            Options
          </Text>
          <View className="bg-gray-900 rounded-xl mx-5 border border-gray-800 overflow-hidden">
            <Row label="Apply qualification rules">
              <Switch
                value={opts.apply_qualification ?? true}
                onValueChange={(v) => set('apply_qualification', v)}
                trackColor={{ false: '#374151', true: '#4f46e5' }}
                thumbColor="#f1f5f9"
              />
            </Row>
            {/* Profile picker */}
            {profiles.length > 0 && (
              <View className="px-4 py-3">
                <Text className="text-gray-500 text-xs mb-2">Scoring profile</Text>
                <View className="flex-row flex-wrap gap-2">
                  <Pressable
                    className={`rounded-full px-3 py-1.5 border active:opacity-75 ${
                      !opts.profile_slug
                        ? 'bg-indigo-600 border-indigo-500'
                        : 'bg-gray-800 border-gray-700'
                    }`}
                    onPress={() => set('profile_slug', null)}
                  >
                    <Text className={`text-xs font-medium ${!opts.profile_slug ? 'text-white' : 'text-gray-400'}`}>
                      Default
                    </Text>
                  </Pressable>
                  {profiles.map((p) => (
                    <Pressable
                      key={p.id}
                      className={`rounded-full px-3 py-1.5 border active:opacity-75 ${
                        opts.profile_slug === p.slug
                          ? 'bg-indigo-600 border-indigo-500'
                          : 'bg-gray-800 border-gray-700'
                      }`}
                      onPress={() => set('profile_slug', p.slug)}
                    >
                      <Text
                        className={`text-xs font-medium ${
                          opts.profile_slug === p.slug ? 'text-white' : 'text-gray-400'
                        }`}
                      >
                        {p.name}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            )}
          </View>
        </ScrollView>
      </View>
    </Modal>
  )
}

// ── Job Intake Modal ──────────────────────────────────────────────────────────

function IntakeModal({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<IntakeMode>('url')
  const [input, setInput] = useState('')

  const mutation = useMutation({
    mutationFn: () =>
      api.intakeJob(mode === 'url' ? { url: input.trim() } : { text: input.trim() }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['job-tracks'] })
      queryClient.invalidateQueries({ queryKey: ['all-jobs'] })
      setInput('')
      onClose()
      Alert.alert('Added ✓', `Job #${data.job_id} added to your pipeline.`)
    },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  function handleClose() {
    setInput('')
    mutation.reset()
    onClose()
  }

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={handleClose}>
      <Pressable className="flex-1 bg-black/60" onPress={handleClose} />
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
        <View className="bg-gray-900 rounded-t-3xl px-6 pt-5 pb-8 border-t border-gray-800">
          <View className="w-10 h-1 bg-gray-700 rounded-full self-center mb-5" />
          <Text className="text-gray-100 text-lg font-bold mb-4">Add Job</Text>

          <View className="flex-row bg-gray-800 rounded-xl p-1 mb-4">
            {(['url', 'text'] as IntakeMode[]).map((m) => (
              <Pressable
                key={m}
                className={`flex-1 py-2 rounded-lg items-center ${mode === m ? 'bg-gray-700' : ''}`}
                onPress={() => setMode(m)}
              >
                <Text className={`text-sm font-medium ${mode === m ? 'text-gray-100' : 'text-gray-500'}`}>
                  {m === 'url' ? '🔗 Job URL' : '📋 Paste JD'}
                </Text>
              </Pressable>
            ))}
          </View>

          {mode === 'url' ? (
            <TextInput
              className="bg-gray-800 rounded-xl px-4 py-3 text-gray-100 text-sm mb-4"
              value={input}
              onChangeText={setInput}
              placeholder="https://jobs.example.com/..."
              placeholderTextColor="#4b5563"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              autoFocus
            />
          ) : (
            <TextInput
              className="bg-gray-800 rounded-xl px-4 py-3 text-gray-100 text-sm mb-4 min-h-32"
              value={input}
              onChangeText={setInput}
              placeholder="Paste the full job description here…"
              placeholderTextColor="#4b5563"
              multiline
              textAlignVertical="top"
              autoFocus
            />
          )}

          <View className="flex-row gap-3">
            <Pressable
              className="flex-1 bg-indigo-600 rounded-xl py-3.5 items-center active:opacity-75"
              onPress={() => mutation.mutate()}
              disabled={mutation.isPending || input.trim().length < 5}
            >
              {mutation.isPending ? (
                <ActivityIndicator size="small" color="white" />
              ) : (
                <Text className="text-white font-semibold">Add to Pipeline</Text>
              )}
            </Pressable>
            <Pressable
              className="bg-gray-800 rounded-xl px-5 items-center justify-center active:opacity-75"
              onPress={handleClose}
            >
              <Text className="text-gray-400 font-medium">Cancel</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  )
}

// ── Location filter ───────────────────────────────────────────────────────────

function locationMatchesMode(job: Job, mode: FeedLocationMode, homeCity: string): boolean {
  if (mode === 'all') return true
  const loc = (job.location || '').toLowerCase()
  const rt  = job.remote_type || ''
  const isRemote = rt === 'remote' || (!rt && loc.includes('remote')) || !job.location
  if (mode === 'remote') return isRemote
  if (mode === 'local') {
    if (!homeCity) return true
    const city = homeCity.split(',')[0].trim().toLowerCase()
    return city ? loc.includes(city) : true
  }
  return true
}

// ── Digest Mode ───────────────────────────────────────────────────────────────

function DigestView({ locationMode, homeCity }: { locationMode: FeedLocationMode; homeCity: string }) {
  const queryClient = useQueryClient()
  const [showOptions, setShowOptions] = useState(false)

  const { data: profiles = [] } = useQuery({
    queryKey: ['profiles'],
    queryFn: () => api.getProfiles(),
  })

  const {
    data: digests,
    isPending: loadingDigests,
    isError: digestsError,
    error: digestsErrObj,
    refetch: refetchDigests,
  } = useQuery({
    queryKey: ['digests'],
    queryFn: () => api.getDigests(),
  })

  const latestDigest = digests?.[0]

  const { data: digest, isPending: loadingItems, isError: detailError, error: detailErrObj } = useQuery({
    queryKey: ['digest', latestDigest?.id],
    queryFn: () => api.getDigest(latestDigest!.id),
    enabled: !!latestDigest,
  })

  const generateMutation = useMutation({
    mutationFn: (opts: DigestGenerateRequest) => api.generateDigest(opts),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['digests'] })
      setShowOptions(false)
    },
    onError: (e: Error) => Alert.alert('Generate failed', e.message),
  })

  const isLoading = loadingDigests || (!!latestDigest && loadingItems)

  if (digestsError || detailError) {
    const msg = ((digestsError ? digestsErrObj : detailErrObj) as Error)?.message
    return <ErrorState message={msg} onRetry={refetchDigests} />
  }

  const allFreshItems = digest?.fresh       ?? []
  const allGemItems   = digest?.hidden_gems ?? []
  const freshItems  = allFreshItems.filter((i) => locationMatchesMode(i.job, locationMode, homeCity))
  const gemItems    = allGemItems.filter((i)   => locationMatchesMode(i.job, locationMode, homeCity))
  const totalItems  = freshItems.length + gemItems.length

  type Section = { title: string; icon: string; data: DigestLaneItem[] }
  const sections: Section[] = []
  if (freshItems.length > 0) sections.push({ title: 'Fresh', icon: '⚡', data: freshItems })
  if (gemItems.length > 0)   sections.push({ title: 'Hidden Gems', icon: '💎', data: gemItems })

  if (isLoading) {
    return (
      <View className="flex-1 items-center justify-center">
        <ActivityIndicator color="#818cf8" />
      </View>
    )
  }

  const locationLabel =
    locationMode === 'remote' ? '🌍 Remote only' :
    locationMode === 'local'  ? `📍 Near ${homeCity || 'your city'}` :
    null

  const ListHeader = (
    <View className="flex-row items-center justify-between mb-4">
      <View>
        <View className="flex-row items-center gap-2">
          <Text className="text-gray-400 text-xs">Latest digest</Text>
          {locationLabel && (
            <Text className="text-indigo-400 text-xs">{locationLabel}</Text>
          )}
        </View>
        {digest && (
          <Text className="text-gray-600 text-xs mt-0.5">
            {totalItems} jobs · {new Date(digest.generated_at).toLocaleDateString()}
            {digest.digest_type !== 'daily' ? ` · ${digest.digest_type}` : ''}
          </Text>
        )}
        {digest?.stats && (digest.stats.excluded_by_qualification > 0 || digest.stats.dropped_by_cap > 0) && (
          <Text className="text-gray-700 text-xs mt-0.5">
            {[
              digest.stats.excluded_by_qualification > 0
                ? `${digest.stats.excluded_by_qualification} filtered`
                : null,
              digest.stats.dropped_by_cap > 0
                ? `${digest.stats.dropped_by_cap} capped`
                : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </Text>
        )}
      </View>
      <Pressable
        className="bg-indigo-600 rounded-lg px-3 py-2 active:opacity-75"
        onPress={() => setShowOptions(true)}
        disabled={generateMutation.isPending}
      >
        {generateMutation.isPending ? (
          <ActivityIndicator size="small" color="white" />
        ) : (
          <Text className="text-white text-sm font-semibold">⚙ New Digest</Text>
        )}
      </Pressable>
    </View>
  )

  if (sections.length === 0) {
    return (
      <>
        <View className="px-4 pt-4">{ListHeader}</View>
        <EmptyState
          icon="📭"
          title="No jobs in digest"
          subtitle="Tap ⚙ New Digest to build a ranked list from your sources"
        />
        <DigestOptionsModal
          visible={showOptions}
          onClose={() => setShowOptions(false)}
          onGenerate={(opts) => generateMutation.mutate(opts)}
          generating={generateMutation.isPending}
          profiles={profiles}
        />
      </>
    )
  }

  return (
    <>
      <SectionList
        sections={sections}
        keyExtractor={(item) => String(item.job.id)}
        contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
        stickySectionHeadersEnabled={false}
        refreshControl={
          <RefreshControl
            refreshing={false}
            onRefresh={() => queryClient.invalidateQueries({ queryKey: ['digests'] })}
            tintColor="#818cf8"
          />
        }
        ListHeaderComponent={ListHeader}
        renderSectionHeader={({ section }) => (
          <View className="flex-row items-center gap-1.5 mt-4 mb-2">
            <Text className="text-base">{section.icon}</Text>
            <Text className="text-gray-400 text-sm font-semibold">{section.title}</Text>
            <Text className="text-gray-700 text-sm">{section.data.length}</Text>
          </View>
        )}
        renderItem={({ item }: { item: DigestLaneItem }) => (
          <JobCard job={item.job} rankPosition={item.rank_position} />
        )}
      />
      <DigestOptionsModal
        visible={showOptions}
        onClose={() => setShowOptions(false)}
        onGenerate={(opts) => generateMutation.mutate(opts)}
        generating={generateMutation.isPending}
        profiles={profiles}
      />
    </>
  )
}

// ── Browse Mode ───────────────────────────────────────────────────────────────

type AgeFilter   = 'any' | '1d' | '3d' | '7d' | '14d' | '30d'
type ScoreFilter = 'any' | '40' | '60' | '75'
type RemoteFilter = 'any' | 'remote' | 'hybrid' | 'onsite'
type SortFilter  = 'last_seen' | 'ranking' | 'quality'

const AGE_OPTIONS: { value: AgeFilter; label: string }[] = [
  { value: 'any',  label: 'Any age' },
  { value: '1d',   label: 'Today' },
  { value: '3d',   label: '3 days' },
  { value: '7d',   label: '1 week' },
  { value: '14d',  label: '2 weeks' },
  { value: '30d',  label: '1 month' },
]
const SCORE_OPTIONS: { value: ScoreFilter; label: string }[] = [
  { value: 'any', label: 'Any score' },
  { value: '40',  label: '40+ score' },
  { value: '60',  label: '60+ score' },
  { value: '75',  label: '75+ score' },
]
const REMOTE_OPTIONS: { value: RemoteFilter; label: string }[] = [
  { value: 'any',    label: 'Any' },
  { value: 'remote', label: 'Remote' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'onsite', label: 'On-site' },
]
const SORT_OPTIONS: { value: SortFilter; label: string }[] = [
  { value: 'last_seen', label: 'Newest' },
  { value: 'ranking',   label: 'Best match' },
  { value: 'quality',   label: 'Quality' },
]

function ageToDate(age: AgeFilter): string | undefined {
  if (age === 'any') return undefined
  const days = { '1d': 1, '3d': 3, '7d': 7, '14d': 14, '30d': 30 }[age]!
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString()
}

interface FilterPillRowProps<T extends string> {
  options: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
}
function FilterPillRow<T extends string>({ options, value, onChange }: FilterPillRowProps<T>) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} className="flex-row">
      {options.map((o) => {
        const active = o.value === value
        return (
          <Pressable
            key={o.value}
            onPress={() => onChange(o.value)}
            className={`mr-2 px-3 py-1.5 rounded-full border ${
              active
                ? 'bg-indigo-600 border-indigo-500'
                : 'bg-gray-900 border-gray-700'
            }`}
          >
            <Text className={`text-xs font-medium ${active ? 'text-white' : 'text-gray-400'}`}>
              {o.label}
            </Text>
          </Pressable>
        )
      })}
    </ScrollView>
  )
}

function BrowseView({ locationMode }: { locationMode: FeedLocationMode; homeCity: string }) {
  const queryClient = useQueryClient()
  const activeProfileSlug = useConfigStore((s) => s.activeProfileSlug)

  // search input (debounced before hitting backend)
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // filters
  const [age,    setAge]    = useState<AgeFilter>('any')
  const [score,  setScore]  = useState<ScoreFilter>('any')
  const [remote, setRemote] = useState<RemoteFilter>(locationMode === 'remote' ? 'remote' : 'any')
  const [sort,   setSort]   = useState<SortFilter>('last_seen')

  // Sync remote filter pill when feed location mode changes
  useEffect(() => {
    setRemote(locationMode === 'remote' ? 'remote' : 'any')
    setOffset(0)
    setAllJobs([])
  }, [locationMode])

  // pagination
  const [offset, setOffset] = useState(0)
  const [allJobs, setAllJobs] = useState<Job[]>([])

  // debounce search: wait 400 ms after last keystroke
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearchQuery(searchInput.trim())
      setOffset(0)
      setAllJobs([])
    }, 400)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [searchInput])

  // reset paging whenever any filter changes
  function applyFilter<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v)
      setOffset(0)
      setAllJobs([])
    }
  }

  const queryKey = ['all-jobs', offset, activeProfileSlug, searchQuery, age, score, remote, sort]

  const { isPending, isFetching, isError, error } = useQuery({
    queryKey,
    queryFn: async () => {
      const jobs = await api.getJobs({
        limit: BROWSE_LIMIT,
        offset,
        profile_slug: activeProfileSlug ?? undefined,
        q: searchQuery || undefined,
        first_seen_after: ageToDate(age),
        min_score: score !== 'any' ? Number(score) : undefined,
        remote_type: remote !== 'any' ? remote : undefined,
        order: sort,
      })
      setAllJobs((prev) => (offset === 0 ? jobs : [...prev, ...jobs]))
      return jobs
    },
  })

  const hasFilters = searchQuery || age !== 'any' || score !== 'any' || remote !== 'any' || sort !== 'last_seen'

  function refresh() {
    setOffset(0)
    setAllJobs([])
    queryClient.invalidateQueries({ queryKey: ['all-jobs'] })
  }

  if (isPending && allJobs.length === 0) {
    return (
      <View className="flex-1 items-center justify-center">
        <ActivityIndicator color="#818cf8" />
      </View>
    )
  }

  if (isError && allJobs.length === 0) {
    return <ErrorState message={(error as Error)?.message} onRetry={refresh} />
  }

  return (
    <FlatList
      data={allJobs}
      keyExtractor={(j) => String(j.id)}
      contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
      ListHeaderComponent={
        <View className="mb-3 gap-2">
          {/* Search */}
          <TextInput
            className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-2.5 text-gray-100 text-sm"
            value={searchInput}
            onChangeText={setSearchInput}
            placeholder="Search title or company…"
            placeholderTextColor="#4b5563"
            clearButtonMode="while-editing"
          />

          {/* Filter rows */}
          <FilterPillRow options={AGE_OPTIONS}    value={age}    onChange={applyFilter(setAge)} />
          <FilterPillRow options={SCORE_OPTIONS}  value={score}  onChange={applyFilter(setScore)} />
          <FilterPillRow options={REMOTE_OPTIONS} value={remote} onChange={applyFilter(setRemote)} />
          <FilterPillRow options={SORT_OPTIONS}   value={sort}   onChange={applyFilter(setSort)} />

          {/* Result count + clear */}
          <View className="flex-row items-center justify-between mt-0.5">
            <Text className="text-gray-600 text-xs">
              {isFetching && offset === 0 ? 'Loading…' : `${allJobs.length} jobs`}
            </Text>
            {hasFilters && (
              <Pressable
                onPress={() => {
                  setSearchInput('')
                  setSearchQuery('')
                  setAge('any')
                  setScore('any')
                  setRemote('any')
                  setSort('last_seen')
                  setOffset(0)
                  setAllJobs([])
                }}
              >
                <Text className="text-indigo-400 text-xs">Clear filters</Text>
              </Pressable>
            )}
          </View>
        </View>
      }
      renderItem={({ item }) => <JobCard job={item} />}
      ListEmptyComponent={
        <EmptyState
          icon="🔍"
          title={hasFilters ? 'No matches' : 'No jobs yet'}
          subtitle={hasFilters ? 'Try adjusting your filters' : 'Run your collectors to populate jobs'}
        />
      }
      ListFooterComponent={
        allJobs.length >= BROWSE_LIMIT ? (
          <Pressable
            className="bg-gray-900 border border-gray-800 rounded-xl py-3 items-center mt-2 active:opacity-75"
            onPress={() => setOffset((o) => o + BROWSE_LIMIT)}
            disabled={isFetching}
          >
            {isFetching ? (
              <ActivityIndicator size="small" color="#818cf8" />
            ) : (
              <Text className="text-gray-400 text-sm">Load more</Text>
            )}
          </Pressable>
        ) : null
      }
      refreshControl={
        <RefreshControl refreshing={false} onRefresh={refresh} tintColor="#818cf8" />
      }
    />
  )
}

// ── Onboarding Checklist ──────────────────────────────────────────────────────

function OnboardingChecklist() {
  const { onboardingDismissed, setOnboardingDismissed } = useConfigStore()

  const { data: summary } = useQuery({
    queryKey: ['memory-summary'],
    queryFn: () => api.getMemorySummary(),
    staleTime: 60_000,
  })
  const { data: stats } = useQuery({
    queryKey: ['pipeline-stats'],
    queryFn: () => api.getPipelineStats(),
    staleTime: 60_000,
  })

  const hasDoc    = (summary?.facts_total ?? 0) > 0
  const hasApproved = (summary?.facts_approved ?? 0) > 0
  const hasJobs   = (stats?.jobs_active?.total ?? 0) > 0
  const allDone   = hasDoc && hasApproved && hasJobs

  // Auto-dismiss once everything is done
  if (onboardingDismissed || allDone) return null

  const steps: { label: string; done: boolean; tip: string }[] = [
    {
      label: 'Upload a résumé or document',
      done: hasDoc,
      tip: 'Go to Profile → Docs → Upload',
    },
    {
      label: 'Approve at least one career fact',
      done: hasApproved,
      tip: 'Profile → Facts → tap a fact → ✓ Approve',
    },
    {
      label: 'Run Find Jobs',
      done: hasJobs,
      tip: 'Tap the Find Jobs button above',
    },
  ]

  return (
    <View className="mx-4 mt-3 mb-1 bg-gray-900 rounded-xl border border-indigo-800 p-4">
      <View className="flex-row items-center justify-between mb-3">
        <Text className="text-indigo-300 font-semibold text-sm">Getting Started</Text>
        <Pressable onPress={() => setOnboardingDismissed(true)} className="active:opacity-50">
          <Text className="text-gray-500 text-xs">Dismiss</Text>
        </Pressable>
      </View>
      {steps.map((step, i) => (
        <View key={i} className="flex-row items-start gap-2 mb-2">
          <Text className={`text-sm mt-0.5 ${step.done ? 'text-emerald-400' : 'text-gray-600'}`}>
            {step.done ? '✓' : '○'}
          </Text>
          <View className="flex-1">
            <Text className={`text-sm ${step.done ? 'text-gray-500 line-through' : 'text-gray-200'}`}>
              {step.label}
            </Text>
            {!step.done && (
              <Text className="text-gray-500 text-xs mt-0.5">{step.tip}</Text>
            )}
          </View>
        </View>
      ))}
    </View>
  )
}

// ── Main Screen ───────────────────────────────────────────────────────────────

const LOCATION_MODES: { value: FeedLocationMode; label: string }[] = [
  { value: 'remote', label: '🌍 Remote' },
  { value: 'local',  label: '📍 Local'  },
  { value: 'all',    label: '🗺️ All'   },
]

export default function FeedScreen() {
  const [mode, setMode] = useState<FeedMode>('digest')
  const [showIntake, setShowIntake] = useState(false)
  const queryClient = useQueryClient()

  const { feedLocationMode, setFeedLocationMode } = useConfigStore()

  const { data: candidateProfile } = useQuery<CandidateProfile | null>({
    queryKey: ['candidate-profile'],
    queryFn: () => api.getCandidateProfile(),
    staleTime: 60_000,
  })
  const homeCity = candidateProfile?.home_city ?? ''

  const [searching, setSearching] = useState(false)

  // Auto-refresh digest when the app comes back to the foreground (e.g. morning after nightly collection)
  const appStateRef = useRef(AppState.currentState)
  useEffect(() => {
    const sub = AppState.addEventListener('change', (nextState) => {
      if (appStateRef.current.match(/inactive|background/) && nextState === 'active') {
        queryClient.invalidateQueries({ queryKey: ['digests'] })
        queryClient.invalidateQueries({ queryKey: ['all-jobs'] })
      }
      appStateRef.current = nextState
    })
    return () => sub.remove()
  }, [queryClient])

  async function handleFindJobs() {
    if (searching) return
    setSearching(true)
    // Fire-and-forget — don't await, so the user can tab away freely.
    // The server runs the full pipeline; pull-to-refresh when done.
    api.findJobs()
      .then(async (result) => {
        // Rebuild digest so new jobs appear in feed immediately
        await api.generateDigest().catch(() => {})
        queryClient.invalidateQueries({ queryKey: ['digests'] })
        queryClient.invalidateQueries({ queryKey: ['digest'] })
        queryClient.invalidateQueries({ queryKey: ['all-jobs'] })
        const msg = result.new_jobs > 0
          ? `Found ${result.new_jobs} new job${result.new_jobs === 1 ? '' : 's'} in ${Math.round(result.duration_sec)}s`
          : 'No new jobs found this time.'
        Alert.alert('Search complete', msg)
      })
      .catch((e: Error) => {
        Alert.alert('Find Jobs failed', e.message)
      })
      .finally(() => setSearching(false))
  }

  async function handleStopAndDigest() {
    try {
      await api.cancelPipeline()
    } catch {
      // ignore — pipeline will complete naturally
    }
  }

  return (
    <View className="flex-1 bg-gray-950">
      {/* Header */}
      <View className="flex-row items-center px-4 pt-3 pb-2 border-b border-gray-800">
        <View className="flex-row bg-gray-900 rounded-lg p-0.5 flex-1">
          {(['digest', 'browse'] as FeedMode[]).map((m) => (
            <Pressable
              key={m}
              className={`flex-1 py-1.5 rounded-md items-center ${mode === m ? 'bg-gray-700' : ''}`}
              onPress={() => setMode(m)}
            >
              <Text className={`text-sm font-medium ${mode === m ? 'text-gray-100' : 'text-gray-500'}`}>
                {m === 'digest' ? 'Digest' : 'All Jobs'}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Find Jobs / Stop button */}
        {searching ? (
          <Pressable
            className="ml-2 rounded-lg px-3 py-2 active:opacity-75 bg-red-900"
            onPress={handleStopAndDigest}
          >
            <View className="flex-row items-center gap-1.5">
              <ActivityIndicator size="small" color="#fca5a5" />
              <Text className="text-red-300 text-xs font-semibold">Searching…</Text>
            </View>
          </Pressable>
        ) : (
          <Pressable
            className="ml-2 bg-indigo-600 rounded-lg px-3 py-2 active:opacity-75"
            onPress={() => {
              Alert.alert(
                'Find Jobs',
                'Searches all job boards and scores results against your profile. Takes 2–5 minutes — you can use the app freely while it runs.',
                [
                  { text: 'Cancel', style: 'cancel' },
                  { text: 'Start Search', onPress: handleFindJobs },
                ]
              )
            }}
          >
            <Text className="text-white text-xs font-semibold">Find Jobs</Text>
          </Pressable>
        )}

        {/* Manual add button */}
        <Pressable
          className="ml-2 bg-gray-700 rounded-lg px-3 py-2 active:opacity-75"
          onPress={() => setShowIntake(true)}
        >
          <Text className="text-white font-bold text-base leading-none">+</Text>
        </Pressable>
      </View>

      {/* Location mode toggle */}
      <View className="flex-row px-4 pt-2 pb-1 gap-2">
        {LOCATION_MODES.map((lm) => {
          const active = feedLocationMode === lm.value
          const disabled = lm.value === 'local' && !homeCity
          return (
            <Pressable
              key={lm.value}
              onPress={() => !disabled && setFeedLocationMode(lm.value)}
              className={`flex-1 py-1 rounded-lg border items-center active:opacity-75 ${
                active
                  ? 'bg-indigo-700 border-indigo-600'
                  : disabled
                  ? 'bg-gray-900 border-gray-800 opacity-40'
                  : 'bg-gray-900 border-gray-800'
              }`}
            >
              <Text className={`text-xs font-medium ${active ? 'text-white' : 'text-gray-400'}`} numberOfLines={1}>
                {lm.label}
              </Text>
            </Pressable>
          )
        })}
      </View>

      <OnboardingChecklist />
      {mode === 'digest'
        ? <DigestView locationMode={feedLocationMode} homeCity={homeCity} />
        : <BrowseView locationMode={feedLocationMode} homeCity={homeCity} />
      }

      <IntakeModal visible={showIntake} onClose={() => setShowIntake(false)} />
    </View>
  )
}
