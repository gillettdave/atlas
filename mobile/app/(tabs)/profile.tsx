import {
  View,
  Text,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
  Alert,
  RefreshControl,
} from 'react-native'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as DocumentPicker from 'expo-document-picker'
import { api } from '../../services/api'
import { useConfigStore } from '../../stores/config'
import { EmptyState } from '../../components/EmptyState'
import type { CareerFact, ProfileQuestion, TimelineEntry, CandidateProfileUpdate, SearchMode } from '../../types'

// ── Types ──────────────────────────────────────────────────────────────────────

type Tab = 'overview' | 'info' | 'documents' | 'questions' | 'facts' | 'keywords'

// ── Constants ──────────────────────────────────────────────────────────────────

const FACT_ICONS: Record<string, string> = {
  role: '💼', skill: '🛠️', achievement: '🏆', metric: '📊',
  tool: '⚙️', education: '🎓', project: '🚀', narrative: '📖',
  profile_answer: '💬', experience: '🧳',
}

const TABS: { key: Tab; label: string }[] = [
  { key: 'overview',  label: 'Overview'  },
  { key: 'info',      label: 'Info'      },
  { key: 'documents', label: 'Docs'      },
  { key: 'questions', label: 'Questions' },
  { key: 'facts',     label: 'Facts'     },
  { key: 'keywords',  label: 'Keywords'  },
]

// ── Sub-components ────────────────────────────────────────────────────────────

function StatBox({ value, label, color = 'text-gray-100' }: { value: number; label: string; color?: string }) {
  return (
    <View className="flex-1 bg-gray-900 rounded-xl p-3 items-center border border-gray-800">
      <Text className={`text-2xl font-bold ${color}`}>{value}</Text>
      <Text className="text-gray-500 text-xs mt-0.5 text-center">{label}</Text>
    </View>
  )
}

// ── Overview Tab ──────────────────────────────────────────────────────────────

function OverviewTab() {
  const { data: summary, isPending } = useQuery({
    queryKey: ['memory-summary'],
    queryFn: () => api.getMemorySummary(),
  })

  const { data: timeline, isPending: loadingTimeline } = useQuery({
    queryKey: ['timeline'],
    queryFn: () => api.getTimeline(),
  })

  if (isPending || loadingTimeline) {
    return (
      <View className="flex-1 items-center justify-center py-20">
        <ActivityIndicator color="#818cf8" />
      </View>
    )
  }

  const entries: TimelineEntry[] = Array.isArray(timeline)
    ? timeline.filter((e) => e.status !== 'rejected').slice(0, 10)
    : []

  return (
    <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
      {summary && (
        <>
          <Text className="text-gray-500 text-xs uppercase font-semibold tracking-widest mb-3">
            Memory Health
          </Text>
          <View className="flex-row gap-2 mb-2">
            <StatBox value={summary.facts_total}      label="Total Facts"   />
            <StatBox value={summary.facts_approved}   label="Approved"      color="text-emerald-400" />
            <StatBox value={summary.core_proof_points} label="Proof Points" color="text-indigo-400" />
          </View>
          <View className="flex-row gap-2 mb-5">
            <StatBox value={summary.facts_draft}    label="Draft"     color="text-yellow-400" />
            <StatBox value={summary.questions_open} label="Open Qs"   color="text-orange-400" />
            <StatBox value={summary.facts_rejected} label="Rejected"  color="text-red-400" />
          </View>

          {summary.underused_fact_types.length > 0 && (
            <View className="bg-amber-950 border border-amber-900 rounded-xl p-3 mb-5">
              <Text className="text-amber-300 text-sm font-semibold mb-1">💡 Gaps to fill</Text>
              <Text className="text-amber-400 text-xs">
                Underrepresented: {summary.underused_fact_types.join(', ')}
              </Text>
            </View>
          )}
        </>
      )}

      {entries.length > 0 && (
        <>
          <Text className="text-gray-500 text-xs uppercase font-semibold tracking-widest mb-3">
            Career Timeline
          </Text>
          {entries.map((entry) => (
            <View
              key={entry.id}
              className="bg-gray-900 rounded-xl p-4 mb-2 border border-gray-800"
            >
              <Text className="text-gray-100 font-semibold">{entry.title}</Text>
              {entry.company && (
                <Text className="text-gray-400 text-sm mt-0.5">{entry.company}</Text>
              )}
              {(entry.start_date || entry.end_date) && (
                <Text className="text-gray-600 text-xs mt-1">
                  {entry.start_date ?? '?'} → {entry.end_date ?? 'Present'}
                </Text>
              )}
              {entry.summary && (
                <Text className="text-gray-400 text-sm mt-2 leading-relaxed" numberOfLines={3}>
                  {entry.summary}
                </Text>
              )}
            </View>
          ))}
        </>
      )}

      {!summary && entries.length === 0 && (
        <EmptyState icon="🧠" title="No data yet" subtitle="Upload a document to get started" />
      )}
    </ScrollView>
  )
}

// ── Personal Info Tab ─────────────────────────────────────────────────────────

function LabeledField({
  label, value, onChangeText, placeholder, keyboardType, autoCapitalize, multiline,
}: {
  label: string
  value: string
  onChangeText: (t: string) => void
  placeholder?: string
  keyboardType?: 'default' | 'email-address' | 'phone-pad' | 'url'
  autoCapitalize?: 'none' | 'words'
  multiline?: boolean
}) {
  return (
    <View className="mb-4">
      <Text className="text-gray-500 text-xs uppercase font-semibold tracking-wider mb-1.5">
        {label}
      </Text>
      <TextInput
        className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 text-gray-200 text-sm"
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder ?? label}
        placeholderTextColor="#4b5563"
        keyboardType={keyboardType ?? 'default'}
        autoCapitalize={autoCapitalize ?? 'words'}
        multiline={multiline}
        textAlignVertical={multiline ? 'top' : 'center'}
        style={multiline ? { minHeight: 80 } : undefined}
      />
    </View>
  )
}

const SEARCH_MODES: { value: SearchMode; label: string; desc: string }[] = [
  { value: 'remote', label: '🌍 Remote',       desc: 'Remote-only jobs worldwide' },
  { value: 'local',  label: '📍 Local',         desc: 'Jobs near your home city' },
  { value: 'both',   label: '⚡ Both',           desc: 'Remote + local combined' },
  { value: 'target', label: '🎯 Target Cities',  desc: 'Jobs in your target cities' },
  { value: 'all',    label: '🗺️ All',            desc: 'No location filtering' },
]

const RADIUS_OPTIONS = [25, 50, 100, 200]

function PersonalInfoTab() {
  const queryClient = useQueryClient()

  const { data: profile, isPending } = useQuery({
    queryKey: ['candidate-profile'],
    queryFn: () => api.getCandidateProfile(),
  })

  const [form, setForm] = useState<CandidateProfileUpdate>({})
  const [initialised, setInitialised] = useState(false)
  const [targetCityInput, setTargetCityInput] = useState('')

  if (profile !== undefined && !initialised) {
    setForm({
      full_name:        profile?.full_name        ?? '',
      email:            profile?.email            ?? '',
      phone:            profile?.phone            ?? '',
      location:         profile?.location         ?? '',
      linkedin_url:     profile?.linkedin_url     ?? '',
      website_url:      profile?.website_url      ?? '',
      headline:         profile?.headline         ?? '',
      summary:          profile?.summary          ?? '',
      home_city:        profile?.home_city        ?? '',
      search_radius_km: profile?.search_radius_km ?? 50,
      target_cities:    profile?.target_cities    ?? [],
      search_mode:      (profile?.search_mode as SearchMode) ?? 'remote',
    })
    setInitialised(true)
  }

  const saveMutation = useMutation({
    mutationFn: () => api.upsertCandidateProfile(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['candidate-profile'] })
      Alert.alert('Saved', 'Personal info updated.')
    },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const set = (key: keyof CandidateProfileUpdate) => (value: string) =>
    setForm((prev) => ({ ...prev, [key]: value || null }))

  function addTargetCity() {
    const city = targetCityInput.trim()
    if (!city) return
    const existing = form.target_cities ?? []
    if (!existing.includes(city)) {
      setForm((prev) => ({ ...prev, target_cities: [...existing, city] }))
    }
    setTargetCityInput('')
  }

  function removeTargetCity(city: string) {
    setForm((prev) => ({
      ...prev,
      target_cities: (prev.target_cities ?? []).filter((c) => c !== city),
    }))
  }

  if (isPending) {
    return (
      <View className="flex-1 items-center justify-center">
        <ActivityIndicator color="#818cf8" />
      </View>
    )
  }

  const showRadius = form.search_mode === 'local' || form.search_mode === 'both'
  const showTargetCities = form.search_mode === 'target' || form.search_mode === 'all'

  return (
    <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
      <Text className="text-gray-500 text-xs leading-relaxed mb-5">
        This information populates the header and sign-off of generated résumés and cover letters.
      </Text>

      <LabeledField label="Full Name"    value={form.full_name    ?? ''} onChangeText={set('full_name')} />
      <LabeledField label="Headline"     value={form.headline     ?? ''} onChangeText={set('headline')}  placeholder="e.g. Community Manager · Web3 · 8 yrs" />
      <LabeledField label="Email"        value={form.email        ?? ''} onChangeText={set('email')}     keyboardType="email-address" autoCapitalize="none" />
      <LabeledField label="Phone"        value={form.phone        ?? ''} onChangeText={set('phone')}     keyboardType="phone-pad"     autoCapitalize="none" />
      <LabeledField label="Location"     value={form.location     ?? ''} onChangeText={set('location')}  placeholder="e.g. New York, NY (Remote)" />
      <LabeledField label="LinkedIn URL" value={form.linkedin_url ?? ''} onChangeText={set('linkedin_url')} keyboardType="url" autoCapitalize="none" placeholder="https://linkedin.com/in/yourname" />
      <LabeledField label="Website"      value={form.website_url  ?? ''} onChangeText={set('website_url')}  keyboardType="url" autoCapitalize="none" placeholder="https://yoursite.com" />
      <LabeledField label="Professional Summary" value={form.summary ?? ''} onChangeText={set('summary')} multiline placeholder="Optional — overrides the AI summary if set" />

      {/* ── Location Search ──────────────────────────────────────────────── */}
      <View className="mt-2 mb-4">
        <Text className="text-gray-500 text-xs uppercase font-semibold tracking-widest mb-3">
          Job Search Location
        </Text>

        {/* Search mode picker */}
        <Text className="text-gray-500 text-xs uppercase font-semibold tracking-wider mb-1.5">
          Search Mode
        </Text>
        <View className="flex-row flex-wrap gap-2 mb-4">
          {SEARCH_MODES.map(({ value, label }) => (
            <Pressable
              key={value}
              className={`rounded-full px-3 py-1.5 active:opacity-75 ${
                form.search_mode === value ? 'bg-indigo-600' : 'bg-gray-800'
              }`}
              onPress={() => setForm((prev) => ({ ...prev, search_mode: value }))}
            >
              <Text className={`text-sm ${form.search_mode === value ? 'text-white' : 'text-gray-400'}`}>
                {label}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Home city — shown for local/both */}
        {showRadius && (
          <LabeledField
            label="Home City"
            value={form.home_city ?? ''}
            onChangeText={set('home_city')}
            placeholder="e.g. Halifax, NS"
          />
        )}

        {/* Radius picker — shown for local/both */}
        {showRadius && (
          <View className="mb-4">
            <Text className="text-gray-500 text-xs uppercase font-semibold tracking-wider mb-1.5">
              Search Radius
            </Text>
            <View className="flex-row gap-2">
              {RADIUS_OPTIONS.map((km) => (
                <Pressable
                  key={km}
                  className={`flex-1 rounded-xl py-2.5 items-center active:opacity-75 ${
                    form.search_radius_km === km ? 'bg-indigo-600' : 'bg-gray-900 border border-gray-800'
                  }`}
                  onPress={() => setForm((prev) => ({ ...prev, search_radius_km: km }))}
                >
                  <Text className={`text-sm font-medium ${form.search_radius_km === km ? 'text-white' : 'text-gray-400'}`}>
                    {km} km
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
        )}

        {/* Target cities — shown for target/all */}
        {showTargetCities && (
          <View className="mb-4">
            <Text className="text-gray-500 text-xs uppercase font-semibold tracking-wider mb-1.5">
              Target Cities
            </Text>
            {/* Existing city chips */}
            {(form.target_cities ?? []).length > 0 && (
              <View className="flex-row flex-wrap gap-2 mb-2">
                {(form.target_cities ?? []).map((city) => (
                  <Pressable
                    key={city}
                    className="flex-row items-center bg-indigo-900 rounded-full px-3 py-1 gap-1.5 active:opacity-75"
                    onPress={() => removeTargetCity(city)}
                  >
                    <Text className="text-indigo-200 text-sm">{city}</Text>
                    <Text className="text-indigo-400 text-xs">✕</Text>
                  </Pressable>
                ))}
              </View>
            )}
            {/* Add city input */}
            <View className="flex-row gap-2">
              <TextInput
                className="flex-1 bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 text-gray-200 text-sm"
                value={targetCityInput}
                onChangeText={setTargetCityInput}
                placeholder="Add a city (e.g. Austin, TX)"
                placeholderTextColor="#4b5563"
                onSubmitEditing={addTargetCity}
                returnKeyType="done"
              />
              <Pressable
                className="bg-indigo-600 rounded-xl px-4 items-center justify-center active:opacity-75"
                onPress={addTargetCity}
              >
                <Text className="text-white font-semibold">Add</Text>
              </Pressable>
            </View>
          </View>
        )}
      </View>

      <Pressable
        className="bg-indigo-600 rounded-xl py-3.5 items-center mt-2 active:opacity-75"
        onPress={() => saveMutation.mutate()}
        disabled={saveMutation.isPending}
      >
        {saveMutation.isPending ? (
          <ActivityIndicator size="small" color="white" />
        ) : (
          <Text className="text-white font-semibold">Save</Text>
        )}
      </Pressable>
    </ScrollView>
  )
}

// ── Documents Tab ─────────────────────────────────────────────────────────────

function DocumentsTab() {
  const queryClient = useQueryClient()
  const [uploading, setUploading] = useState(false)

  const { data: documents, isPending, refetch } = useQuery({
    queryKey: ['career-documents'],
    queryFn: () => api.getDocuments(),
  })

  const [reExtractingId, setReExtractingId] = useState<number | null>(null)

  const reExtractMutation = useMutation({
    mutationFn: (docId: number) => api.reExtractFacts(docId),
    onMutate: (docId) => setReExtractingId(docId),
    onSuccess: (result) => {
      setReExtractingId(null)
      queryClient.invalidateQueries({ queryKey: ['career-facts'] })
      queryClient.invalidateQueries({ queryKey: ['memory-summary'] })
      Alert.alert('Re-extraction Complete ✓', `${result.new_facts} new draft facts created.`)
    },
    onError: (e: Error) => {
      setReExtractingId(null)
      Alert.alert('Re-extraction Failed', e.message)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (docId: number) => api.deleteDocument(docId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['career-documents'] })
      queryClient.invalidateQueries({ queryKey: ['career-facts'] })
      queryClient.invalidateQueries({ queryKey: ['memory-summary'] })
    },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  function confirmDelete(docId: number, name: string) {
    Alert.alert(
      'Delete document?',
      `"${name}" and all facts extracted from it will be permanently deleted.`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: () => deleteMutation.mutate(docId) },
      ]
    )
  }

  async function pickAndUpload() {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: [
          'application/pdf',
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          'text/plain',
        ],
        copyToCacheDirectory: true,
      })

      if (result.canceled || !result.assets?.[0]) return

      const asset = result.assets[0]
      setUploading(true)

      await api.uploadDocument(
        asset.uri,
        asset.name,
        asset.mimeType ?? 'application/octet-stream'
      )

      queryClient.invalidateQueries({ queryKey: ['career-documents'] })
      queryClient.invalidateQueries({ queryKey: ['career-facts'] })
      queryClient.invalidateQueries({ queryKey: ['memory-summary'] })
      Alert.alert('Uploaded', `"${asset.name}" ingested. Facts will appear in the Facts tab.`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Upload failed'
      Alert.alert('Upload failed', msg)
    } finally {
      setUploading(false)
    }
  }

  const docs = Array.isArray(documents) ? documents : []

  return (
    <ScrollView
      contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
      refreshControl={<RefreshControl refreshing={false} onRefresh={refetch} tintColor="#818cf8" />}
    >
      <Pressable
        className="bg-indigo-600 rounded-xl py-3.5 items-center mb-5 active:opacity-75"
        onPress={pickAndUpload}
        disabled={uploading}
      >
        {uploading ? (
          <View className="flex-row items-center gap-2">
            <ActivityIndicator size="small" color="white" />
            <Text className="text-white font-semibold">Uploading…</Text>
          </View>
        ) : (
          <Text className="text-white font-semibold">+ Upload Résumé / Document</Text>
        )}
      </Pressable>

      {isPending ? (
        <ActivityIndicator color="#818cf8" />
      ) : docs.length === 0 ? (
        <EmptyState
          icon="📄"
          title="No documents yet"
          subtitle="Upload a PDF, DOCX, or TXT to extract your career facts"
        />
      ) : (
        docs.map((doc) => (
          <View
            key={doc.id}
            className="bg-gray-900 rounded-xl p-4 mb-2 border border-gray-800"
          >
            <View className="flex-row items-start justify-between">
              <Text className="text-gray-100 font-medium flex-1 mr-3" numberOfLines={2}>
                {doc.name}
              </Text>
              <View className="flex-row items-center gap-2">
                <View className="bg-gray-800 rounded px-2 py-0.5">
                  <Text className="text-gray-500 text-xs">
                    {doc.content_type?.includes('pdf') ? 'PDF'
                      : doc.content_type?.includes('word') ? 'DOCX'
                      : 'TXT'}
                  </Text>
                </View>
                <Pressable
                  onPress={() =>
                    Alert.alert(
                      'Re-extract Facts',
                      'This will delete all draft facts from this document and re-run AI extraction. Approved and rejected facts are kept.',
                      [
                        { text: 'Cancel', style: 'cancel' },
                        { text: 'Re-extract', onPress: () => reExtractMutation.mutate(doc.id) },
                      ]
                    )
                  }
                  disabled={reExtractingId === doc.id}
                  className="p-1 active:opacity-50"
                >
                  {reExtractingId === doc.id ? (
                    <ActivityIndicator size="small" color="#818cf8" />
                  ) : (
                    <Text className="text-indigo-400 text-sm">🔄</Text>
                  )}
                </Pressable>
                <Pressable
                  onPress={() => confirmDelete(doc.id, doc.name)}
                  disabled={deleteMutation.isPending}
                  className="p-1 active:opacity-50"
                >
                  <Text className="text-red-500 text-sm">🗑</Text>
                </Pressable>
              </View>
            </View>
            {doc.preview && (
              <Text className="text-gray-500 text-xs mt-2 leading-relaxed" numberOfLines={3}>
                {doc.preview}
              </Text>
            )}
            {doc.ingested_at && (
              <Text className="text-gray-700 text-xs mt-2">
                {new Date(doc.ingested_at).toLocaleDateString()}
              </Text>
            )}
          </View>
        ))
      )}
    </ScrollView>
  )
}

// ── Questions Tab ─────────────────────────────────────────────────────────────

function QuestionCard({ question }: { question: ProfileQuestion }) {
  const [expanded, setExpanded] = useState(false)
  const [answer, setAnswer] = useState('')
  const queryClient = useQueryClient()

  const answerMutation = useMutation({
    mutationFn: () => api.answerQuestion(question.id, answer),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['questions'] })
      queryClient.invalidateQueries({ queryKey: ['career-facts'] })
      queryClient.invalidateQueries({ queryKey: ['memory-summary'] })
    },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const dismissMutation = useMutation({
    mutationFn: () => api.dismissQuestion(question.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['questions'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteQuestion(question.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['questions'] })
      queryClient.invalidateQueries({ queryKey: ['memory-summary'] })
    },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const priorityColor =
    question.priority === 'high' ? 'text-red-400'
    : question.priority === 'medium' ? 'text-yellow-400'
    : 'text-gray-500'

  return (
    <View className="bg-gray-900 rounded-xl mb-3 border border-gray-800 overflow-hidden">
      <Pressable className="p-4 active:opacity-75" onPress={() => setExpanded((e) => !e)}>
        <View className="flex-row items-start justify-between gap-2">
          <Text className="text-gray-200 text-sm leading-relaxed flex-1">
            {question.question_text}
          </Text>
          <Text className="text-gray-600 text-lg">{expanded ? '▲' : '▼'}</Text>
        </View>
        <View className="flex-row items-center gap-2 mt-2">
          <Text className={`text-xs font-medium ${priorityColor}`}>
            {question.priority}
          </Text>
          <Text className="text-gray-700 text-xs">·</Text>
          <Text className="text-gray-600 text-xs capitalize">
            {question.question_type.replace(/_/g, ' ')}
          </Text>
          {question.job_title && (
            <>
              <Text className="text-gray-700 text-xs">·</Text>
              <Text className="text-gray-600 text-xs" numberOfLines={1}>
                {question.job_title}
              </Text>
            </>
          )}
        </View>
      </Pressable>

      {expanded && (
        <View className="px-4 pb-4 border-t border-gray-800">
          <TextInput
            className="bg-gray-800 rounded-lg p-3 text-gray-200 text-sm mt-3 min-h-20"
            value={answer}
            onChangeText={setAnswer}
            placeholder="Type your answer… (8+ words for auto-approval)"
            placeholderTextColor="#4b5563"
            multiline
            textAlignVertical="top"
          />
          <View className="flex-row gap-2 mt-3">
            <Pressable
              className="flex-1 bg-indigo-600 rounded-lg py-2.5 items-center active:opacity-75"
              onPress={() => answerMutation.mutate()}
              disabled={answerMutation.isPending || answer.trim().length === 0}
            >
              {answerMutation.isPending ? (
                <ActivityIndicator size="small" color="white" />
              ) : (
                <Text className="text-white text-sm font-semibold">Save Answer</Text>
              )}
            </Pressable>
            <Pressable
              className="bg-gray-800 rounded-lg py-2.5 px-4 items-center active:opacity-75"
              onPress={() => dismissMutation.mutate()}
              disabled={dismissMutation.isPending}
            >
              <Text className="text-gray-400 text-sm">Dismiss</Text>
            </Pressable>
            <Pressable
              className="bg-red-950 rounded-lg py-2.5 px-3 items-center active:opacity-75"
              onPress={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
            >
              <Text className="text-red-400 text-sm">🗑</Text>
            </Pressable>
          </View>
        </View>
      )}
    </View>
  )
}

function QuestionsTab() {
  const queryClient = useQueryClient()

  const { data: questions, isPending, refetch } = useQuery({
    queryKey: ['questions'],
    queryFn: () => api.getQuestions(),
  })

  const generateMutation = useMutation({
    mutationFn: () => api.generateQuestions(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['questions'] })
      queryClient.invalidateQueries({ queryKey: ['memory-summary'] })
    },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const openQuestions = Array.isArray(questions)
    ? questions.filter((q) => q.status === 'open')
    : []

  return (
    <ScrollView
      contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
      refreshControl={<RefreshControl refreshing={false} onRefresh={refetch} tintColor="#818cf8" />}
    >
      <Pressable
        className="bg-gray-800 rounded-xl py-3.5 items-center mb-4 border border-gray-700 active:opacity-75"
        onPress={() => generateMutation.mutate()}
        disabled={generateMutation.isPending}
      >
        {generateMutation.isPending ? (
          <View className="flex-row items-center gap-2">
            <ActivityIndicator size="small" color="#818cf8" />
            <Text className="text-indigo-300 font-semibold">Generating…</Text>
          </View>
        ) : (
          <Text className="text-indigo-300 font-semibold">✦ Generate Gap Questions</Text>
        )}
      </Pressable>

      {isPending ? (
        <ActivityIndicator color="#818cf8" />
      ) : openQuestions.length === 0 ? (
        <EmptyState
          icon="✅"
          title="No open questions"
          subtitle="Tap Generate to have AI identify gaps in your career memory"
        />
      ) : (
        <>
          <Text className="text-gray-500 text-xs mb-3">
            {openQuestions.length} open — tap a question to answer it
          </Text>
          {openQuestions.map((q) => (
            <QuestionCard key={q.id} question={q} />
          ))}
        </>
      )}
    </ScrollView>
  )
}

// ── Fact Card ─────────────────────────────────────────────────────────────────

function FactCard({ fact }: { fact: CareerFact }) {
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draftText, setDraftText] = useState(fact.fact_text)
  const queryClient = useQueryClient()

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['career-facts'] })
    queryClient.invalidateQueries({ queryKey: ['memory-summary'] })
  }

  const updateMutation = useMutation({
    mutationFn: (patch: { verification_state?: string; is_core_proof_point?: number; fact_text?: string }) =>
      api.updateFact(fact.id, patch),
    onSuccess: () => { invalidate(); setEditing(false) },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteFact(fact.id),
    onSuccess: invalidate,
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const stateColor =
    fact.verification_state === 'approved' ? 'text-emerald-400'
    : fact.verification_state === 'rejected' ? 'text-red-400'
    : 'text-yellow-400'

  const stateBg =
    fact.verification_state === 'approved' ? 'bg-emerald-950'
    : fact.verification_state === 'rejected' ? 'bg-red-950'
    : 'bg-yellow-950'

  const borderColor =
    fact.verification_state === 'approved' ? 'border-emerald-900'
    : fact.verification_state === 'rejected' ? 'border-red-900'
    : 'border-gray-800'

  return (
    <View className={`bg-gray-900 rounded-xl mb-2 border ${borderColor} overflow-hidden`}>
      {/* Header row — tap to expand */}
      <Pressable className="p-3 active:opacity-75" onPress={() => { setExpanded(e => !e); setEditing(false) }}>
        <View className="flex-row items-start gap-2">
          <Text className="text-gray-300 text-sm leading-relaxed flex-1">
            {fact.fact_text}
          </Text>
          {fact.is_core_proof_point === 1 && (
            <Text className="text-indigo-400 text-xs mt-0.5">⭐</Text>
          )}
          <Text className="text-gray-600 text-sm">{expanded ? '▲' : '▼'}</Text>
        </View>
        <View className="flex-row items-center gap-2 mt-1.5">
          <View className={`rounded px-1.5 py-0.5 ${stateBg}`}>
            <Text className={`text-xs ${stateColor}`}>{fact.verification_state}</Text>
          </View>
          {fact.text_edited_at && (
            <View className="rounded px-1.5 py-0.5 bg-gray-800">
              <Text className="text-gray-500 text-xs">edited</Text>
            </View>
          )}
          <Text className="text-gray-700 text-xs">
            {Math.round(fact.confidence_score * 100)}% confidence
          </Text>
        </View>
      </Pressable>

      {/* Expanded action area */}
      {expanded && (
        <View className="border-t border-gray-800 px-3 pb-3">
          {/* Edit text area */}
          {editing ? (
            <View className="mt-3">
              <TextInput
                className="bg-gray-800 rounded-lg p-3 text-gray-200 text-sm min-h-16"
                value={draftText}
                onChangeText={setDraftText}
                multiline
                textAlignVertical="top"
                autoFocus
              />
              <View className="flex-row gap-2 mt-2">
                <Pressable
                  className="flex-1 bg-indigo-600 rounded-lg py-2.5 items-center active:opacity-75"
                  onPress={() => updateMutation.mutate({ fact_text: draftText.trim() })}
                  disabled={updateMutation.isPending || !draftText.trim()}
                >
                  {updateMutation.isPending
                    ? <ActivityIndicator size="small" color="white" />
                    : <Text className="text-white text-sm font-semibold">Save</Text>
                  }
                </Pressable>
                <Pressable
                  className="bg-gray-800 rounded-lg py-2.5 px-4 items-center active:opacity-75"
                  onPress={() => { setEditing(false); setDraftText(fact.fact_text) }}
                >
                  <Text className="text-gray-400 text-sm">Cancel</Text>
                </Pressable>
              </View>
            </View>
          ) : (
            <View className="flex-row gap-2 mt-3 flex-wrap">
              {/* Approve */}
              {fact.verification_state !== 'approved' && (
                <Pressable
                  className="bg-emerald-900 rounded-lg py-2 px-3 items-center active:opacity-75"
                  onPress={() => updateMutation.mutate({ verification_state: 'approved' })}
                  disabled={updateMutation.isPending}
                >
                  <Text className="text-emerald-300 text-sm font-medium">✓ Approve</Text>
                </Pressable>
              )}
              {/* Reject / Demote */}
              {fact.verification_state !== 'rejected' && (
                <Pressable
                  className="bg-red-950 rounded-lg py-2 px-3 items-center active:opacity-75"
                  onPress={() => updateMutation.mutate({ verification_state: 'rejected' })}
                  disabled={updateMutation.isPending}
                >
                  <Text className="text-red-400 text-sm font-medium">✗ Reject</Text>
                </Pressable>
              )}
              {/* Restore draft */}
              {fact.verification_state !== 'draft' && (
                <Pressable
                  className="bg-yellow-950 rounded-lg py-2 px-3 items-center active:opacity-75"
                  onPress={() => updateMutation.mutate({ verification_state: 'draft' })}
                  disabled={updateMutation.isPending}
                >
                  <Text className="text-yellow-400 text-sm font-medium">↩ Draft</Text>
                </Pressable>
              )}
              {/* Star toggle */}
              <Pressable
                className={`rounded-lg py-2 px-3 items-center active:opacity-75 ${
                  fact.is_core_proof_point === 1 ? 'bg-indigo-900' : 'bg-gray-800'
                }`}
                onPress={() => updateMutation.mutate({ is_core_proof_point: fact.is_core_proof_point === 1 ? 0 : 1 })}
                disabled={updateMutation.isPending}
              >
                <Text className={`text-sm ${fact.is_core_proof_point === 1 ? 'text-indigo-300' : 'text-gray-500'}`}>
                  ⭐ Key fact
                </Text>
              </Pressable>
              {/* Edit */}
              <Pressable
                className="bg-gray-800 rounded-lg py-2 px-3 items-center active:opacity-75"
                onPress={() => setEditing(true)}
              >
                <Text className="text-gray-400 text-sm">✏️ Edit</Text>
              </Pressable>
              {/* Delete */}
              <Pressable
                className="bg-red-950 rounded-lg py-2 px-3 items-center active:opacity-75"
                onPress={() =>
                  Alert.alert('Delete fact?', fact.fact_text.slice(0, 80) + (fact.fact_text.length > 80 ? '…' : ''), [
                    { text: 'Cancel', style: 'cancel' },
                    { text: 'Delete', style: 'destructive', onPress: () => deleteMutation.mutate() },
                  ])
                }
                disabled={deleteMutation.isPending}
              >
                {deleteMutation.isPending
                  ? <ActivityIndicator size="small" color="#f87171" />
                  : <Text className="text-red-400 text-sm">🗑</Text>
                }
              </Pressable>
            </View>
          )}
          {updateMutation.isPending && !editing && (
            <ActivityIndicator size="small" color="#818cf8" style={{ marginTop: 8 }} />
          )}
        </View>
      )}
    </View>
  )
}

// ── Facts Tab ─────────────────────────────────────────────────────────────────

type FactFilter = 'all' | 'draft' | 'approved' | 'rejected'

const FACT_FILTERS: { value: FactFilter; label: string }[] = [
  { value: 'all',      label: 'All'      },
  { value: 'draft',    label: 'Draft'    },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
]

function FactsTab() {
  const [filter, setFilter] = useState<FactFilter>('all')

  const { data: facts, isPending, refetch } = useQuery({
    queryKey: ['career-facts'],
    queryFn: () => api.getCareerFacts(),
  })

  const allFacts: CareerFact[] = Array.isArray(facts) ? facts : []

  const approved = allFacts.filter(f => f.verification_state === 'approved')
  const draft    = allFacts.filter(f => f.verification_state === 'draft')
  const rejected = allFacts.filter(f => f.verification_state === 'rejected')

  const visibleFacts = filter === 'all' ? allFacts
    : filter === 'draft'    ? draft
    : filter === 'approved' ? approved
    : rejected

  const grouped = visibleFacts.reduce<Record<string, CareerFact[]>>((acc, fact) => {
    const key = fact.fact_type ?? 'other'
    ;(acc[key] ??= []).push(fact)
    return acc
  }, {})

  const sections = Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b))

  if (isPending) {
    return (
      <View className="flex-1 items-center justify-center py-20">
        <ActivityIndicator color="#818cf8" />
      </View>
    )
  }

  if (allFacts.length === 0) {
    return (
      <EmptyState
        icon="📋"
        title="No facts yet"
        subtitle="Upload a document or answer questions to build your career memory"
      />
    )
  }

  return (
    <ScrollView
      contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
      refreshControl={<RefreshControl refreshing={false} onRefresh={refetch} tintColor="#818cf8" />}
    >
      {/* Summary counts — tappable to filter */}
      <View className="flex-row gap-3 mb-3">
        <Pressable
          className={`flex-1 rounded-lg p-2.5 border items-center active:opacity-75 ${
            filter === 'approved' ? 'bg-emerald-950 border-emerald-800' : 'bg-gray-900 border-gray-800'
          }`}
          onPress={() => setFilter(f => f === 'approved' ? 'all' : 'approved')}
        >
          <Text className="text-emerald-400 font-semibold text-base">{approved.length}</Text>
          <Text className="text-gray-600 text-xs mt-0.5">approved</Text>
        </Pressable>
        <Pressable
          className={`flex-1 rounded-lg p-2.5 border items-center active:opacity-75 ${
            filter === 'draft' ? 'bg-yellow-950 border-yellow-800' : 'bg-gray-900 border-gray-800'
          }`}
          onPress={() => setFilter(f => f === 'draft' ? 'all' : 'draft')}
        >
          <Text className="text-yellow-400 font-semibold text-base">{draft.length}</Text>
          <Text className="text-gray-600 text-xs mt-0.5">draft</Text>
        </Pressable>
        <Pressable
          className={`flex-1 rounded-lg p-2.5 border items-center active:opacity-75 ${
            filter === 'rejected' ? 'bg-red-950 border-red-900' : 'bg-gray-900 border-gray-800'
          }`}
          onPress={() => setFilter(f => f === 'rejected' ? 'all' : 'rejected')}
        >
          <Text className="text-red-400 font-semibold text-base">{rejected.length}</Text>
          <Text className="text-gray-600 text-xs mt-0.5">rejected</Text>
        </Pressable>
      </View>

      {/* Filter pills */}
      <View className="flex-row gap-2 mb-4">
        {FACT_FILTERS.map(({ value, label }) => (
          <Pressable
            key={value}
            className={`rounded-full px-3 py-1 active:opacity-75 ${
              filter === value ? 'bg-indigo-600' : 'bg-gray-800'
            }`}
            onPress={() => setFilter(value)}
          >
            <Text className={`text-xs font-medium ${
              filter === value ? 'text-white' : 'text-gray-400'
            }`}>
              {label}
            </Text>
          </Pressable>
        ))}
      </View>

      {visibleFacts.length === 0 && (
        <View className="items-center py-10">
          <Text className="text-gray-600 text-sm">No {filter} facts</Text>
        </View>
      )}

      {sections.map(([type, items]) => (
        <View key={type} className="mb-5">
          <View className="flex-row items-center gap-2 mb-2">
            <Text className="text-base">{FACT_ICONS[type] ?? '📌'}</Text>
            <Text className="text-gray-300 font-semibold capitalize">
              {type.replace(/_/g, ' ')}
            </Text>
            <Text className="text-gray-700 text-sm">({items.length})</Text>
          </View>
          {items.map((fact) => (
            <FactCard key={fact.id} fact={fact} />
          ))}
        </View>
      ))}
    </ScrollView>
  )
}

// ── Keywords Tab ──────────────────────────────────────────────────────────────

type KeywordList = 'strong_keywords' | 'weak_keywords' | 'negative_keywords'

const KEYWORD_SECTIONS: { key: KeywordList; label: string; color: string; chipBg: string; chipText: string }[] = [
  { key: 'strong_keywords',   label: 'Strong',   color: 'text-emerald-400', chipBg: 'bg-emerald-950 border-emerald-800', chipText: 'text-emerald-300' },
  { key: 'weak_keywords',     label: 'Weak',     color: 'text-yellow-400',  chipBg: 'bg-yellow-950 border-yellow-800',   chipText: 'text-yellow-300'  },
  { key: 'negative_keywords', label: 'Negative', color: 'text-red-400',     chipBg: 'bg-red-950 border-red-900',         chipText: 'text-red-300'     },
]

function KeywordsTab() {
  const queryClient = useQueryClient()
  const { activeProfileSlug } = useConfigStore()
  const slug = activeProfileSlug ?? 'david'

  const [addingFor, setAddingFor] = useState<KeywordList | null>(null)
  const [draftAdd, setDraftAdd] = useState('')
  const [regenerating, setRegenerating] = useState(false)

  const { data: profile, isPending, refetch } = useQuery({
    queryKey: ['profile-detail', slug],
    queryFn: () => api.getProfile(slug),
  })

  async function saveKeywords(update: Partial<Record<KeywordList, string[]>>) {
    await api.updateProfile(slug, update)
    queryClient.invalidateQueries({ queryKey: ['profile-detail', slug] })
    refetch()
  }

  function removeKeyword(list: KeywordList, word: string) {
    if (!profile) return
    const current: string[] = profile[list] ?? []
    saveKeywords({ [list]: current.filter(k => k !== word) }).catch(() =>
      Alert.alert('Error', 'Failed to remove keyword')
    )
  }

  function addKeyword(list: KeywordList) {
    const word = draftAdd.trim().toLowerCase()
    if (!word || !profile) return
    const current: string[] = profile[list] ?? []
    if (current.includes(word)) {
      Alert.alert('Already exists', `"${word}" is already in this list.`)
      return
    }
    saveKeywords({ [list]: [...current, word] })
      .then(() => { setDraftAdd(''); setAddingFor(null) })
      .catch(() => Alert.alert('Error', 'Failed to add keyword'))
  }

  async function regenerate() {
    setRegenerating(true)
    try {
      const result = await api.generateProfileKeywords(slug)
      queryClient.invalidateQueries({ queryKey: ['profile-detail', slug] })
      refetch()
      Alert.alert(
        'Keywords Regenerated ✓',
        `From ${result.facts_used} approved facts:\n\nStrong: ${result.strong_keywords.length} · Weak: ${result.weak_keywords.length} · Negative: ${result.negative_keywords.length}`
      )
    } catch (e: unknown) {
      Alert.alert('Failed', e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setRegenerating(false)
    }
  }

  if (isPending) {
    return (
      <View className="flex-1 items-center justify-center py-20">
        <ActivityIndicator color="#818cf8" />
      </View>
    )
  }

  return (
    <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
      {/* Regenerate button */}
      <Pressable
        className="flex-row items-center justify-center gap-2 bg-indigo-600 rounded-xl py-3 mb-6 active:opacity-75"
        onPress={regenerate}
        disabled={regenerating}
      >
        {regenerating
          ? <ActivityIndicator size="small" color="white" />
          : <Text className="text-white font-semibold">✨ Regenerate with AI</Text>
        }
      </Pressable>

      {KEYWORD_SECTIONS.map(({ key, label, color, chipBg, chipText }) => {
        const words: string[] = profile?.[key] ?? []
        const isAdding = addingFor === key

        return (
          <View key={key} className="mb-6">
            <View className="flex-row items-center justify-between mb-2">
              <Text className={`text-xs uppercase font-semibold tracking-widest ${color}`}>
                {label} ({words.length})
              </Text>
              <Pressable
                className="px-2 py-1 active:opacity-50"
                onPress={() => { setAddingFor(isAdding ? null : key); setDraftAdd('') }}
              >
                <Text className="text-indigo-400 text-sm font-semibold">{isAdding ? 'Cancel' : '+ Add'}</Text>
              </Pressable>
            </View>

            {/* Add input */}
            {isAdding && (
              <View className="flex-row gap-2 mb-2">
                <TextInput
                  className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 text-sm"
                  placeholder="e.g. community manager"
                  placeholderTextColor="#4b5563"
                  value={draftAdd}
                  onChangeText={setDraftAdd}
                  autoFocus
                  autoCapitalize="none"
                  onSubmitEditing={() => addKeyword(key)}
                  returnKeyType="done"
                />
                <Pressable
                  className="bg-indigo-600 rounded-lg px-4 items-center justify-center active:opacity-75"
                  onPress={() => addKeyword(key)}
                  disabled={!draftAdd.trim()}
                >
                  <Text className="text-white font-semibold text-sm">Add</Text>
                </Pressable>
              </View>
            )}

            {/* Keyword chips */}
            <View className="flex-row flex-wrap gap-2">
              {words.length === 0 && (
                <Text className="text-gray-700 text-sm italic">No keywords yet</Text>
              )}
              {words.map((word) => (
                <View key={word} className={`flex-row items-center rounded-full border px-3 py-1 gap-1.5 ${chipBg}`}>
                  <Text className={`text-xs ${chipText}`}>{word}</Text>
                  <Pressable
                    onPress={() => removeKeyword(key, word)}
                    hitSlop={8}
                    className="active:opacity-50"
                  >
                    <Text className={`text-xs ${chipText} opacity-60`}>✕</Text>
                  </Pressable>
                </View>
              ))}
            </View>
          </View>
        )
      })}
    </ScrollView>
  )
}

// ── Main Screen ───────────────────────────────────────────────────────────────

export default function ProfileScreen() {
  const [activeTab, setActiveTab] = useState<Tab>('overview')

  return (
    <View className="flex-1 bg-gray-950">
      {/* Tab bar */}
      <View className="flex-row border-b border-gray-800 px-2">
        {TABS.map((tab) => (
          <Pressable
            key={tab.key}
            className={`flex-1 py-3 items-center ${
              activeTab === tab.key ? 'border-b-2 border-indigo-500' : ''
            }`}
            onPress={() => setActiveTab(tab.key)}
          >
            <Text
              className={
                activeTab === tab.key
                  ? 'text-indigo-400 font-semibold text-sm'
                  : 'text-gray-600 text-sm'
              }
            >
              {tab.label}
            </Text>
          </Pressable>
        ))}
      </View>

      {/* Tab content */}
      {activeTab === 'overview'  && <OverviewTab />}
      {activeTab === 'info'      && <PersonalInfoTab />}
      {activeTab === 'documents' && <DocumentsTab />}
      {activeTab === 'questions' && <QuestionsTab />}
      {activeTab === 'facts'     && <FactsTab />}
      {activeTab === 'keywords'  && <KeywordsTab />}
    </View>
  )
}
