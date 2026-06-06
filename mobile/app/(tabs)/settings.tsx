import {
  View,
  Text,
  TextInput,
  Pressable,
  ScrollView,
  Alert,
  ActivityIndicator,
} from 'react-native'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'expo-router'
import { useConfigStore } from '../../stores/config'
import { api } from '../../services/api'
import type { CollectorSchedule } from '../../types'

function SectionHeader({ title }: { title: string }) {
  return (
    <Text className="text-gray-500 text-xs uppercase font-semibold tracking-widest mb-3">
      {title}
    </Text>
  )
}

type FrequencyOption = 'off' | '1x' | '2x' | '3x' | '4x'

const FREQUENCY_LABELS: Record<FrequencyOption, string> = {
  off: 'Off',
  '1x': '1×/day',
  '2x': '2×/day',
  '3x': '3×/day',
  '4x': '4×/day',
}

function scheduleToFrequency(schedule: CollectorSchedule | undefined): FrequencyOption {
  if (!schedule || !schedule.is_active) return 'off'
  if (schedule.cadence === 'daily') return '1x'
  if (schedule.cadence === 'every_n_minutes' && schedule.interval_minutes === 360) return '4x'
  if (schedule.cadence === 'cron') {
    if (schedule.cron_expression === '0 8,20 * * *') return '2x'
    if (schedule.cron_expression === '0 8,14,20 * * *') return '3x'
  }
  return '1x'
}

function BucketRow({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View className="flex-row items-center justify-between px-4 py-2.5 border-b border-gray-800">
      <Text className="text-gray-400 text-sm">{label}</Text>
      <Text className={`font-semibold text-sm ${color}`}>{value}</Text>
    </View>
  )
}

export default function SettingsScreen() {
  const router = useRouter()
  const { apiBase, adminToken, activeProfileId, setApiBase, setAdminToken, setActiveProfile } =
    useConfigStore()

  const [draftBase, setDraftBase] = useState(apiBase)
  const [draftToken, setDraftToken] = useState(adminToken)
  const [testing, setTesting] = useState(false)
  const [rescoring, setRescoring] = useState(false)

  const queryClient = useQueryClient()

  const { data: profiles } = useQuery({
    queryKey: ['profiles'],
    queryFn: () => api.getProfiles(),
  })

  const { data: stats } = useQuery({
    queryKey: ['pipeline-stats'],
    queryFn: () => api.getPipelineStats(),
    retry: false,
  })

  const { data: collectorSchedules } = useQuery({
    queryKey: ['collector-schedules'],
    queryFn: () => api.getCollectorSchedules(),
    retry: false,
  })

  const activeCollectorSchedule = collectorSchedules?.find(s => s.is_active) ?? collectorSchedules?.[0]
  const [savingFreq, setSavingFreq] = useState(false)

  async function setCollectionFrequency(freq: FrequencyOption) {
    setSavingFreq(true)
    try {
      const existing = activeCollectorSchedule

      if (freq === 'off') {
        if (existing) {
          await api.updateCollectorSchedule(existing.id, { is_active: false })
        }
      } else {
        const configs: Record<FrequencyOption, object> = {
          off: {},
          '1x': { cadence: 'daily', hour_utc: 9, minute_utc: 0, cron_expression: null, interval_minutes: null },
          '2x': { cadence: 'cron', cron_expression: '0 8,20 * * *', hour_utc: null, minute_utc: null, interval_minutes: null },
          '3x': { cadence: 'cron', cron_expression: '0 8,14,20 * * *', hour_utc: null, minute_utc: null, interval_minutes: null },
          '4x': { cadence: 'every_n_minutes', interval_minutes: 360, cron_expression: null, hour_utc: null, minute_utc: null },
        }
        const patch = { ...configs[freq], is_active: true, then_import: true, then_rank: true, then_digest: true }

        if (existing) {
          await api.updateCollectorSchedule(existing.id, patch)
        } else {
          await api.createCollectorSchedule({ name: 'Auto Collection', ...patch } as Parameters<typeof api.createCollectorSchedule>[0])
        }
      }
      queryClient.invalidateQueries({ queryKey: ['collector-schedules'] })
    } catch (e: unknown) {
      Alert.alert('Error', e instanceof Error ? e.message : 'Failed to save schedule')
    } finally {
      setSavingFreq(false)
    }
  }

  function save() {
    setApiBase(draftBase.trim())
    setAdminToken(draftToken.trim())
    queryClient.clear()
    Alert.alert('Saved', 'Settings updated.')
  }

  async function testConnection() {
    setTesting(true)
    const ok = await api.ping()
    setTesting(false)
    Alert.alert(
      ok ? 'Connected ✓' : 'Unreachable',
      ok ? 'API is reachable.' : 'Could not reach the API. Check the URL and token.'
    )
  }

  async function rescoreAll() {
    Alert.alert(
      'Rescore All Jobs',
      'This will re-rank all 800+ jobs in your database using your current profile and approved facts. It may take a moment.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Rescore',
          onPress: async () => {
            setRescoring(true)
            try {
              const result = await api.rescoreJobs({ onlyUnscored: false })
              queryClient.invalidateQueries({ queryKey: ['pipeline-stats'] })
              Alert.alert(
                'Rescore Complete ✓',
                `Scored ${result.scored} jobs · ${result.hidden_gems} hidden gems found\n\nTop: ${result.by_bucket?.top ?? 0} · Strong: ${result.by_bucket?.strong ?? 0} · Maybe: ${result.by_bucket?.maybe ?? 0}`
              )
            } catch (e: unknown) {
              Alert.alert('Rescore Failed', e instanceof Error ? e.message : 'Unknown error')
            } finally {
              setRescoring(false)
            }
          },
        },
      ]
    )
  }

  return (
    <ScrollView className="flex-1 bg-gray-950" contentContainerStyle={{ padding: 20 }}>

      {/* ── Connection ─────────────────────────────────────── */}
      <SectionHeader title="Connection" />
      <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden mb-4">
        <View className="px-4 pt-4 pb-3">
          <Text className="text-gray-500 text-xs mb-1.5">API Base URL</Text>
          <TextInput
            className="text-gray-100 text-sm"
            value={draftBase}
            onChangeText={setDraftBase}
            placeholder="http://192.168.1.x:8000"
            placeholderTextColor="#374151"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
          />
        </View>
        <View className="h-px bg-gray-800" />
        <View className="px-4 pt-3 pb-4">
          <Text className="text-gray-500 text-xs mb-1.5">Admin Token</Text>
          <TextInput
            className="text-gray-100 text-sm"
            value={draftToken}
            onChangeText={setDraftToken}
            placeholder="optional"
            placeholderTextColor="#374151"
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
          />
        </View>
      </View>

      <View className="flex-row gap-3 mb-8">
        <Pressable
          className="flex-1 bg-indigo-600 rounded-xl py-3 items-center active:opacity-75"
          onPress={save}
        >
          <Text className="text-white font-semibold">Save</Text>
        </Pressable>
        <Pressable
          className="flex-1 bg-gray-800 rounded-xl py-3 items-center active:opacity-75"
          onPress={testConnection}
          disabled={testing}
        >
          {testing ? (
            <ActivityIndicator size="small" color="#9ca3af" />
          ) : (
            <Text className="text-gray-300 font-semibold">Test</Text>
          )}
        </Pressable>
      </View>

      {/* ── Pipeline Stats ─────────────────────────────────── */}
      {stats && (
        <>
          <SectionHeader title="Pipeline Overview" />
          <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden mb-2">
            <BucketRow label="🏆 Top jobs"        value={stats.jobs_active.top}    color="text-emerald-400" />
            <BucketRow label="💪 Strong"          value={stats.jobs_active.strong} color="text-indigo-400" />
            <BucketRow label="🤔 Maybe"           value={stats.jobs_active.maybe}  color="text-yellow-400" />
            <BucketRow label="⏭ Skip"             value={stats.jobs_active.skip}   color="text-gray-500" />
            <View className="flex-row items-center justify-between px-4 py-2.5">
              <Text className="text-gray-400 text-sm">Total active</Text>
              <Text className="text-gray-300 font-semibold text-sm">{stats.jobs_active.total}</Text>
            </View>
          </View>

          {(stats.pending_raw_events > 0 || stats.needs_review > 0) && (
            <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden mb-2">
              {stats.pending_raw_events > 0 && (
                <View className="flex-row items-center justify-between px-4 py-2.5 border-b border-gray-800">
                  <Text className="text-gray-400 text-sm">Pending raw events</Text>
                  <Text className="text-yellow-400 font-semibold text-sm">{stats.pending_raw_events}</Text>
                </View>
              )}
              {stats.needs_review > 0 && (
                <View className="flex-row items-center justify-between px-4 py-2.5">
                  <Text className="text-gray-400 text-sm">Needs review</Text>
                  <Text className="text-orange-400 font-semibold text-sm">{stats.needs_review}</Text>
                </View>
              )}
            </View>
          )}

          {stats.latest_digest && (
            <View className="bg-gray-900 rounded-xl border border-gray-800 px-4 py-3 mb-2">
              <Text className="text-gray-500 text-xs mb-1">Latest digest</Text>
              <Text className="text-gray-300 text-sm">
                {stats.latest_digest.item_count} jobs · {stats.latest_digest.digest_type}
              </Text>
              <Text className="text-gray-600 text-xs mt-0.5">
                {new Date(stats.latest_digest.generated_at).toLocaleString()}
              </Text>
            </View>
          )}

          <View className="mb-8" />
        </>
      )}

      {/* ── Data Tools ─────────────────────────────────────── */}
      <SectionHeader title="Data Tools" />
      <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden mb-8">
        <Pressable
          className="flex-row items-center justify-between px-4 py-3.5 active:opacity-75"
          onPress={rescoreAll}
          disabled={rescoring}
        >
          <View className="flex-1 mr-3">
            <Text className="text-gray-200 font-medium">Rescore All Jobs</Text>
            <Text className="text-gray-500 text-xs mt-0.5">
              Re-rank every job using your current profile and approved facts
            </Text>
          </View>
          {rescoring ? (
            <ActivityIndicator size="small" color="#818cf8" />
          ) : (
            <Text className="text-indigo-400 text-sm font-semibold">Run</Text>
          )}
        </Pressable>
      </View>

      {/* ── Collection Schedule ────────────────────────────── */}
      <SectionHeader title="Collection Schedule" />
      <View className="bg-gray-900 rounded-xl border border-gray-800 px-4 pt-4 pb-3 mb-2">
        <Text className="text-gray-400 text-xs mb-3">
          How often to auto-collect jobs from all sources. Each run takes up to 30 minutes.
        </Text>
        <View className="flex-row gap-2 flex-wrap">
          {(['off', '1x', '2x', '3x', '4x'] as FrequencyOption[]).map(opt => {
            const selected = scheduleToFrequency(activeCollectorSchedule) === opt
            return (
              <Pressable
                key={opt}
                onPress={() => setCollectionFrequency(opt)}
                disabled={savingFreq}
                className={`px-3 py-1.5 rounded-lg border ${
                  selected
                    ? 'bg-indigo-600 border-indigo-500'
                    : 'bg-gray-800 border-gray-700'
                } active:opacity-70`}
              >
                <Text className={`text-sm font-medium ${selected ? 'text-white' : 'text-gray-400'}`}>
                  {FREQUENCY_LABELS[opt]}
                </Text>
              </Pressable>
            )
          })}
          {savingFreq && <ActivityIndicator size="small" color="#818cf8" />}
        </View>
        {activeCollectorSchedule?.next_run_at && scheduleToFrequency(activeCollectorSchedule) !== 'off' && (
          <Text className="text-gray-600 text-xs mt-3">
            Next run: {new Date(activeCollectorSchedule.next_run_at).toLocaleString()}
          </Text>
        )}
        {activeCollectorSchedule?.last_run_at && (
          <Text className="text-gray-600 text-xs mt-0.5">
            Last run: {new Date(activeCollectorSchedule.last_run_at).toLocaleString()}
            {activeCollectorSchedule.last_status ? ` · ${activeCollectorSchedule.last_status}` : ''}
          </Text>
        )}
      </View>
      <View className="mb-8" />

      {/* ── Activity ───────────────────────────────────────── */}
      <SectionHeader title="Activity" />
      <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden mb-8">
        <Pressable
          className="flex-row items-center justify-between px-4 py-3.5 border-b border-gray-800 active:opacity-75"
          onPress={() => router.push('/feedback')}
        >
          <Text className="text-gray-200">Feedback Log</Text>
          <Text className="text-gray-600">›</Text>
        </Pressable>
        <Pressable
          className="flex-row items-center justify-between px-4 py-3.5 border-b border-gray-800 active:opacity-75"
          onPress={() => router.push('/schedules')}
        >
          <Text className="text-gray-200">Delivery Schedules</Text>
          <Text className="text-gray-600">›</Text>
        </Pressable>
        <Pressable
          className="flex-row items-center justify-between px-4 py-3.5 active:opacity-75"
          onPress={() => router.push('/qualification')}
        >
          <Text className="text-gray-200">Qualification Rules</Text>
          <Text className="text-gray-600">›</Text>
        </Pressable>
      </View>

      {/* ── Scoring Profile ────────────────────────────────── */}
      {profiles && profiles.length > 0 && (
        <>
          <SectionHeader title="Active Scoring Profile" />
          <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden mb-8">
            {profiles.map((profile, i) => (
              <Pressable
                key={profile.id}
                className={`flex-row items-center justify-between px-4 py-3 active:opacity-75 ${
                  i < profiles.length - 1 ? 'border-b border-gray-800' : ''
                }`}
                onPress={() => {
                  const toggling = activeProfileId === profile.id
                  setActiveProfile(toggling ? null : profile.id, toggling ? null : profile.slug)
                }}
              >
                <View>
                  <Text className="text-gray-200 font-medium">{profile.display_name}</Text>
                  <Text className="text-gray-600 text-xs mt-0.5">{profile.slug}</Text>
                </View>
                {activeProfileId === profile.id && (
                  <Text className="text-indigo-400 text-sm font-semibold">Active</Text>
                )}
              </Pressable>
            ))}
          </View>
        </>
      )}

      {/* ── About ─────────────────────────────────────────── */}
      <SectionHeader title="About" />
      <View className="bg-gray-900 rounded-xl border border-gray-800 px-4 py-3">
        <Text className="text-gray-400 text-sm">Atlas Mobile v1.0</Text>
        <Text className="text-gray-700 text-xs mt-1">Personal AI job search engine</Text>
      </View>

      <View className="h-8" />
    </ScrollView>
  )
}
