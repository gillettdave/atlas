import {
  View,
  Text,
  TextInput,
  Pressable,
  ScrollView,
  Alert,
  ActivityIndicator,
} from 'react-native'
import { useState, useRef, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'expo-router'
import { useConfigStore } from '../../stores/config'
import { api } from '../../services/api'

function SectionHeader({ title }: { title: string }) {
  return (
    <Text className="text-gray-500 text-xs uppercase font-semibold tracking-widest mb-3">
      {title}
    </Text>
  )
}

function BucketRow({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View className="flex-row items-center justify-between px-4 py-2.5 border-b border-gray-800">
      <Text className="text-gray-400 text-sm">{label}</Text>
      <Text className={`font-semibold text-sm ${color}`}>{value}</Text>
    </View>
  )
}

function formatRelativeTime(isoString: string | null): string {
  if (!isoString) return 'Never'
  const date = new Date(isoString)
  const diffMs = Date.now() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.floor(diffHours / 24)
  return `${diffDays}d ago`
}

function formatTimeUntil(isoString: string | null): string {
  if (!isoString) return '—'
  const date = new Date(isoString)
  const diffMs = date.getTime() - Date.now()
  if (diffMs <= 0) return 'soon'
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 60) return `in ${diffMins}m`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `in ${diffHours}h`
  const diffDays = Math.floor(diffHours / 24)
  return `in ${diffDays}d`
}

export default function SettingsScreen() {
  const router = useRouter()
  const { apiBase, adminToken, activeProfileId, activeProfileSlug, devMode, setApiBase, setAdminToken, setActiveProfile, setDevMode } =
    useConfigStore()

  const [draftBase, setDraftBase] = useState(apiBase)
  const [draftToken, setDraftToken] = useState(adminToken)
  const [testing, setTesting] = useState(false)
  const [rescoring, setRescoring] = useState(false)
  const [generatingKeywords, setGeneratingKeywords] = useState(false)
  const [refreshingDigest, setRefreshingDigest] = useState(false)
  const [expiringJobs, setExpiringJobs] = useState(false)
  const [bgBanner, setBgBanner] = useState<string | null>(null)
  const versionTapCount = useRef(0)
  const versionTapTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const bgRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (bgRefreshTimer.current) clearTimeout(bgRefreshTimer.current) }, [])

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

  const { data: collectionStatus } = useQuery({
    queryKey: ['collection-status'],
    queryFn: () => api.getCollectionStatus(),
    retry: false,
    refetchInterval: 5 * 60 * 1000, // refresh every 5 mins
  })

  function showBgBanner(message: string, refreshAfterMs: number) {
    setBgBanner(message)
    if (bgRefreshTimer.current) clearTimeout(bgRefreshTimer.current)
    bgRefreshTimer.current = setTimeout(() => {
      queryClient.invalidateQueries({ queryKey: ['digests'] })
      queryClient.invalidateQueries({ queryKey: ['digest'] })
      queryClient.invalidateQueries({ queryKey: ['all-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['pipeline-stats'] })
      setBgBanner(null)
    }, refreshAfterMs)
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
      'Re-ranks all jobs against your current profile and approved facts.\n\nTakes ~30 seconds — runs in the background so you can use the app freely.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Rescore',
          onPress: () => {
            setRescoring(true)
            api.rescoreJobsAsync({ onlyUnscored: false })
              .then(() => api.generateDigestAsync())
              .catch(() => {})
              .finally(() => setRescoring(false))
            showBgBanner('Scoring jobs in background… feed refreshes in ~30s', 35_000)
          },
        },
      ]
    )
  }

  async function generateKeywords() {
    const slug = activeProfileSlug
    if (!slug) {
      Alert.alert('No active profile', 'Select a profile first.')
      return
    }
    Alert.alert(
      'Regenerate Keywords',
      'Uses AI to analyse your approved facts and build new keyword lists, then rescores all jobs.\n\nKeyword generation takes ~5 seconds. Rescoring runs in the background (~30s).',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Generate',
          onPress: async () => {
            setGeneratingKeywords(true)
            try {
              const result = await api.generateProfileKeywords(slug)
              // Keywords done — fire rescore + digest in background
              api.rescoreJobsAsync({ onlyUnscored: false })
                .then(() => api.generateDigestAsync())
                .catch(() => {})
              showBgBanner('Keywords saved — scoring jobs in background… feed refreshes in ~30s', 35_000)
              Alert.alert(
                'Keywords Generated ✓',
                `From ${result.facts_used} facts:\n\nStrong: ${result.strong_keywords.length} · Weak: ${result.weak_keywords.length} · Negative: ${result.negative_keywords.length}\n\nRescoring jobs in background.`
              )
            } catch (e: unknown) {
              Alert.alert('Keyword Generation Failed', e instanceof Error ? e.message : 'Unknown error')
            } finally {
              setGeneratingKeywords(false)
            }
          },
        },
      ]
    )
  }

  function handleVersionTap() {
    versionTapCount.current += 1
    if (versionTapTimer.current) clearTimeout(versionTapTimer.current)
    if (versionTapCount.current >= 5) {
      versionTapCount.current = 0
      const next = !devMode
      setDevMode(next)
      Alert.alert(next ? '🛠 Developer mode on' : 'Developer mode off', next ? 'Dev tools unlocked.' : 'Dev tools hidden.')
    } else {
      versionTapTimer.current = setTimeout(() => { versionTapCount.current = 0 }, 2000)
    }
  }

  async function refreshDigest() {
    Alert.alert(
      'Refresh Feed',
      'Rebuilds your digest from the current job scores.\n\nTakes ~5 seconds — runs in the background.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Refresh',
          onPress: () => {
            setRefreshingDigest(true)
            api.generateDigestAsync({ digest_type: 'daily' })
              .catch(() => {})
              .finally(() => setRefreshingDigest(false))
            showBgBanner('Rebuilding feed in background… refreshes in ~10s', 12_000)
          },
        },
      ]
    )
  }

  return (
    <ScrollView className="flex-1 bg-gray-950" contentContainerStyle={{ padding: 20 }}>

      {/* ── Background task banner ──────────────────────────── */}
      {bgBanner && (
        <View className="flex-row items-center justify-between bg-indigo-900 border border-indigo-700 rounded-xl px-4 py-3 mb-4">
          <View className="flex-row items-center gap-2 flex-1">
            <ActivityIndicator size="small" color="#a5b4fc" />
            <Text className="text-indigo-200 text-sm flex-1">{bgBanner}</Text>
          </View>
          <Pressable onPress={() => setBgBanner(null)} className="ml-2 active:opacity-50">
            <Text className="text-indigo-400 text-xs">✕</Text>
          </Pressable>
        </View>
      )}

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

      {/* ── Feed Status ────────────────────────────────────── */}
      <SectionHeader title="Feed Status" />
      <View className="bg-gray-900 rounded-xl border border-gray-800 px-4 py-3 mb-8">
        {collectionStatus ? (
          <>
            <View className="flex-row items-center justify-between mb-2">
              <Text className="text-gray-400 text-sm">Jobs in database</Text>
              <Text className="text-gray-200 font-semibold text-sm">
                {collectionStatus.total_active_jobs.toLocaleString()}
              </Text>
            </View>
            <View className="flex-row items-center justify-between mb-2">
              <Text className="text-gray-400 text-sm">Last updated</Text>
              <Text className="text-gray-300 text-sm">
                {formatRelativeTime(collectionStatus.last_collected_at)}
              </Text>
            </View>
            <View className="flex-row items-center justify-between">
              <Text className="text-gray-400 text-sm">Next update</Text>
              <Text className="text-gray-300 text-sm">
                {formatTimeUntil(collectionStatus.next_run_at)}
              </Text>
            </View>
          </>
        ) : (
          <Text className="text-gray-600 text-sm">Loading feed status…</Text>
        )}
      </View>

      {/* ── Pipeline Stats ─────────────────────────────────── */}
      {stats && (
        <>
          <SectionHeader title="Pipeline Overview" />
          <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden mb-2">
            <BucketRow label="💪 Strong"          value={stats.jobs_active.strong} color="text-indigo-400" />
            <BucketRow label="🤔 Maybe"           value={stats.jobs_active.maybe}  color="text-yellow-400" />
            <BucketRow label="⏭ Skip"             value={stats.jobs_active.skip}   color="text-gray-500" />
            <View className="flex-row items-center justify-between px-4 py-2.5">
              <Text className="text-gray-400 text-sm">Total active</Text>
              <Text className="text-gray-300 font-semibold text-sm">{stats.jobs_active.total}</Text>
            </View>
          </View>

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
          className="flex-row items-center justify-between px-4 py-3.5 border-b border-gray-800 active:opacity-75"
          onPress={refreshDigest}
          disabled={refreshingDigest}
        >
          <View className="flex-1 mr-3">
            <Text className="text-gray-200 font-medium">Refresh Feed</Text>
            <Text className="text-gray-500 text-xs mt-0.5">
              Rebuild your digest from the latest jobs
            </Text>
          </View>
          {refreshingDigest ? (
            <ActivityIndicator size="small" color="#818cf8" />
          ) : (
            <Text className="text-indigo-400 text-sm font-semibold">Run</Text>
          )}
        </Pressable>
        <Pressable
          className="flex-row items-center justify-between px-4 py-3.5 border-b border-gray-800 active:opacity-75"
          onPress={generateKeywords}
          disabled={generatingKeywords}
        >
          <View className="flex-1 mr-3">
            <Text className="text-gray-200 font-medium">Regenerate Keywords</Text>
            <Text className="text-gray-500 text-xs mt-0.5">
              Use AI to extract scoring keywords from your approved career facts
            </Text>
          </View>
          {generatingKeywords ? (
            <ActivityIndicator size="small" color="#818cf8" />
          ) : (
            <Text className="text-indigo-400 text-sm font-semibold">Run</Text>
          )}
        </Pressable>
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
      <Pressable
        className="bg-gray-900 rounded-xl border border-gray-800 px-4 py-3"
        onPress={handleVersionTap}
        accessibilityLabel="App version — tap 5 times to unlock developer mode"
      >
        <View className="flex-row items-center justify-between">
          <Text className="text-gray-400 text-sm">Atlas Mobile v1.0</Text>
          {devMode && (
            <Text className="text-yellow-500 text-xs font-semibold">DEV</Text>
          )}
        </View>
        <Text className="text-gray-700 text-xs mt-1">Personal AI job search engine</Text>
      </Pressable>

      {/* ── Developer Tools (hidden behind 5-tap) ─────────── */}
      {devMode && collectionStatus && (
        <>
          <View className="mt-8" />
          <SectionHeader title="Developer Tools" />
          <View className="bg-gray-900 rounded-xl border border-yellow-900 overflow-hidden mb-3">
            <View className="px-4 py-3 border-b border-gray-800">
              <Text className="text-yellow-500 text-xs font-semibold mb-2">Collection Status</Text>
              <View className="flex-row justify-between mb-1">
                <Text className="text-gray-500 text-xs">Boards total</Text>
                <Text className="text-gray-300 text-xs">{collectionStatus.boards_total}</Text>
              </View>
              <View className="flex-row justify-between mb-1">
                <Text className="text-gray-500 text-xs">Fresh (≤3d)</Text>
                <Text className="text-emerald-400 text-xs">{collectionStatus.boards_fresh}</Text>
              </View>
              <View className="flex-row justify-between mb-1">
                <Text className="text-gray-500 text-xs">Collected 24h</Text>
                <Text className="text-indigo-400 text-xs">{collectionStatus.boards_collected_24h}</Text>
              </View>
              <View className="flex-row justify-between">
                <Text className="text-gray-500 text-xs">Blocklisted</Text>
                <Text className="text-red-400 text-xs">{collectionStatus.boards_blocklisted}</Text>
              </View>
            </View>
            <View className="px-4 py-3 border-b border-gray-800">
              <View className="flex-row justify-between mb-1">
                <Text className="text-gray-500 text-xs">Scheduler status</Text>
                <Text className="text-gray-300 text-xs">{collectionStatus.status}</Text>
              </View>
              <View className="flex-row justify-between">
                <Text className="text-gray-500 text-xs">Next run</Text>
                <Text className="text-gray-300 text-xs">{formatTimeUntil(collectionStatus.next_run_at)}</Text>
              </View>
            </View>
            <Pressable
              className="px-4 py-3.5 active:opacity-75"
              onPress={() => {
                queryClient.invalidateQueries({ queryKey: ['collection-status'] })
                queryClient.invalidateQueries({ queryKey: ['pipeline-stats'] })
                Alert.alert('Refreshed', 'Status data reloaded.')
              }}
            >
              <Text className="text-yellow-500 text-sm font-medium">Refresh Status Data</Text>
            </Pressable>
          </View>
          <Pressable
            className="bg-gray-900 rounded-xl border border-yellow-900 px-4 py-3.5 mb-3 active:opacity-75"
            disabled={expiringJobs}
            onPress={() => {
              Alert.alert(
                'Expire Stale Jobs',
                'Soft-expires board jobs older than 30 days, ATS jobs older than 60 days, and hard-deletes inactive jobs older than 120 days (protected if you\'ve interacted with them).\n\nThis runs automatically after each daily collection.',
                [
                  { text: 'Cancel', style: 'cancel' },
                  {
                    text: 'Run Now',
                    onPress: async () => {
                      setExpiringJobs(true)
                      try {
                        const r = await api.expireJobs()
                        Alert.alert(
                          'Expiry Complete ✓',
                          `Soft-expired: ${r.soft_expired_board} board + ${r.soft_expired_ats} ATS jobs\nHard-deleted: ${r.hard_deleted} jobs\nProtected: ${r.protected_from_delete} jobs (you applied)`
                        )
                        queryClient.invalidateQueries({ queryKey: ['pipeline-stats'] })
                      } catch (e: unknown) {
                        Alert.alert('Failed', e instanceof Error ? e.message : 'Unknown error')
                      } finally {
                        setExpiringJobs(false)
                      }
                    },
                  },
                ]
              )
            }}
          >
            <View className="flex-row items-center justify-between">
              <Text className="text-yellow-500 text-sm font-medium">Expire Stale Jobs</Text>
              {expiringJobs
                ? <ActivityIndicator size="small" color="#eab308" />
                : <Text className="text-yellow-700 text-xs">30d board / 60d ATS / 120d delete</Text>
              }
            </View>
          </Pressable>
          <Pressable
            className="bg-gray-900 rounded-xl border border-yellow-900 px-4 py-3.5 mb-3 active:opacity-75"
            onPress={() => {
              Alert.alert(
                'Disable Dev Mode',
                'Hide developer tools?',
                [
                  { text: 'Cancel', style: 'cancel' },
                  { text: 'Disable', style: 'destructive', onPress: () => setDevMode(false) },
                ]
              )
            }}
          >
            <Text className="text-red-400 text-sm font-medium">Disable Developer Mode</Text>
          </Pressable>
        </>
      )}

      <View className="h-8" />
    </ScrollView>
  )
}
