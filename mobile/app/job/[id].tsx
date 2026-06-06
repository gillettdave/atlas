import {
  View,
  Text,
  ScrollView,
  Pressable,
  Linking,
  ActivityIndicator,
  Alert,
} from 'react-native'
import { useLocalSearchParams, useRouter, Stack } from 'expo-router'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../services/api'
import { ScoreBadge } from '../../components/ScoreBadge'
import { StageTag } from '../../components/StageTag'
import { ErrorState } from '../../components/ErrorState'
import { useConfigStore } from '../../stores/config'
import type { JobReaction } from '../../types'

const REACTIONS: { key: JobReaction; label: string; icon: string }[] = [
  { key: 'saved',     label: 'Save',    icon: '🔖' },
  { key: 'applied',   label: 'Applied', icon: '✅' },
  { key: 'dismissed', label: 'Skip',    icon: '👋' },
]

export default function JobDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const router = useRouter()
  const queryClient = useQueryClient()
  const jobId = id as string
  const { activeProfileSlug } = useConfigStore()

  const [activeReaction, setActiveReaction] = useState<JobReaction | null>(null)

  // ── Job data ──────────────────────────────────────────────────────────────

  const { data: job, isPending, isError, error, refetch } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.getJob(jobId),
  })

  // ── Pipeline awareness ────────────────────────────────────────────────────
  // Uses cached data from the Pipeline tab — only fetches if cache is stale.

  const { data: tracks } = useQuery({
    queryKey: ['job-tracks'],
    queryFn: () => api.getJobTracks(),
    staleTime: 60_000,   // reuse cache for 60 s
  })

  const existingTrack = tracks?.find((t) => t.job_id === jobId) ?? null

  // ── Mutations ──────────────────────────────────────────────────────────────

  const feedbackMutation = useMutation({
    mutationFn: async (reaction: JobReaction) => {
      await api.submitFeedback(jobId, reaction, activeProfileSlug ?? undefined)
      // Saving a job also adds it to the pipeline (idempotent — ignores 409 if already tracked)
      if (reaction === 'saved' && !existingTrack) {
        try {
          await api.addJobTrack(jobId, 'saved')
        } catch {
          // 409 = already tracked, that's fine
        }
      }
    },
    onSuccess: (_, reaction) => {
      setActiveReaction(reaction)
      queryClient.invalidateQueries({ queryKey: ['feedback'] })
      queryClient.invalidateQueries({ queryKey: ['job-tracks'] })
    },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const intakeMutation = useMutation({
    mutationFn: () => api.addJobTrack(jobId, 'saved'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['job-tracks'] })
      Alert.alert('Added ✓', 'Job is now in your pipeline.')
    },
    onError: (e: Error) => {
      // 409 = already tracked
      if (e.message.includes('409') || e.message.includes('track_already_exists')) {
        queryClient.invalidateQueries({ queryKey: ['job-tracks'] })
        Alert.alert('Already added', 'This job is already in your pipeline.')
      } else {
        Alert.alert('Error', e.message)
      }
    },
  })

  // ── Loading state ─────────────────────────────────────────────────────────

  if (isPending) {
    return (
      <View className="flex-1 bg-gray-950 items-center justify-center">
        <ActivityIndicator color="#818cf8" />
      </View>
    )
  }

  if (isError) {
    return (
      <View className="flex-1 bg-gray-950">
        <ErrorState message={(error as Error)?.message} onRetry={refetch} />
      </View>
    )
  }

  if (!job) {
    return (
      <View className="flex-1 bg-gray-950 items-center justify-center">
        <ActivityIndicator color="#818cf8" />
      </View>
    )
  }

  const pendingReaction = feedbackMutation.isPending ? feedbackMutation.variables : null

  return (
    <>
      <Stack.Screen
        options={{
          headerShown: true,
          headerStyle: { backgroundColor: '#030712' },
          headerTintColor: '#f1f5f9',
          headerShadowVisible: false,
          headerTitle: job.company,
          headerBackTitle: 'Back',
        }}
      />

      <ScrollView
        className="flex-1 bg-gray-950"
        contentContainerStyle={{ padding: 20 }}
      >
        {/* ── Pipeline banner ─────────────────────────────────── */}
        {existingTrack && (
          <View className="flex-row items-center gap-3 bg-gray-900 rounded-xl px-4 py-3 mb-4 border border-indigo-900">
            <Text className="text-gray-400 text-sm">In pipeline</Text>
            <StageTag stage={existingTrack.stage ?? 'new'} />
            {existingTrack.updated_at && (
              <Text className="text-gray-700 text-xs ml-auto">
                {new Date(existingTrack.updated_at).toLocaleDateString()}
              </Text>
            )}
          </View>
        )}

        {/* ── Title & company ─────────────────────────────────── */}
        <Text className="text-gray-100 text-2xl font-bold leading-tight">
          {job.title}
        </Text>
        <Text className="text-gray-400 text-base mt-1">{job.company}</Text>

        {/* ── Location / remote pills ─────────────────────────── */}
        <View className="flex-row flex-wrap gap-2 mt-3">
          {job.location && (
            <View className="bg-gray-800 rounded-full px-3 py-1">
              <Text className="text-gray-400 text-xs">📍 {job.location}</Text>
            </View>
          )}
          {job.remote_type && (
            <View className="bg-gray-800 rounded-full px-3 py-1">
              <Text className="text-gray-400 text-xs capitalize">
                {job.remote_type.replace(/_/g, ' ')}
              </Text>
            </View>
          )}
        </View>

        {/* ── Scores ──────────────────────────────────────────── */}
        <View className="flex-row gap-3 mt-4">
          <ScoreBadge score={job.quality_score} label="Quality" />
          <ScoreBadge score={job.ranking_score} label="Rank" />
        </View>

        {/* ── Reaction row ────────────────────────────────────── */}
        <View className="flex-row gap-2 mt-5">
          {REACTIONS.map((r) => {
            const isActive  = activeReaction === r.key
            const isLoading = pendingReaction === r.key
            return (
              <Pressable
                key={r.key}
                className={`flex-1 rounded-xl py-3 items-center border active:opacity-75 ${
                  isActive
                    ? 'bg-indigo-600 border-indigo-500'
                    : 'bg-gray-900 border-gray-800'
                }`}
                onPress={() => feedbackMutation.mutate(r.key)}
                disabled={feedbackMutation.isPending}
              >
                <Text className={`text-xl ${isLoading ? 'opacity-40' : ''}`}>{r.icon}</Text>
                <Text
                  className={`text-xs mt-0.5 ${
                    isActive ? 'text-indigo-200 font-semibold' : 'text-gray-500'
                  }`}
                >
                  {r.label}
                </Text>
              </Pressable>
            )
          })}
        </View>

        {/* ── CTAs ────────────────────────────────────────────── */}
        <View className="gap-2 mt-3">
          <Pressable
            className="bg-indigo-600 rounded-xl py-3.5 items-center active:opacity-75"
            onPress={() => {
              const url = job.canonical_apply_url || job.apply_url
              if (url) Linking.openURL(url)
              else Alert.alert('No URL', 'No application link available for this job.')
            }}
          >
            <Text className="text-white font-semibold">Open Application →</Text>
          </Pressable>

          {existingTrack ? (
            /* Already in pipeline — link to pipeline tab */
            <Pressable
              className="bg-gray-800 rounded-xl py-3.5 items-center active:opacity-75"
              onPress={() => router.navigate('/(tabs)/pipeline')}
            >
              <Text className="text-indigo-400 font-semibold">View in Pipeline</Text>
            </Pressable>
          ) : (
            /* Not yet tracked — allow intake */
            <Pressable
              className="bg-gray-800 rounded-xl py-3.5 items-center active:opacity-75"
              onPress={() => intakeMutation.mutate()}
              disabled={intakeMutation.isPending}
            >
              {intakeMutation.isPending ? (
                <ActivityIndicator size="small" color="#9ca3af" />
              ) : (
                <Text className="text-gray-300 font-semibold">+ Add to Pipeline</Text>
              )}
            </Pressable>
          )}

          <Pressable
            className="bg-gray-900 rounded-xl py-3.5 items-center border border-gray-800 active:opacity-75"
            onPress={() => router.push(`/application/${jobId}`)}
          >
            <Text className="text-gray-400 font-semibold">View Application Package</Text>
          </Pressable>
        </View>

        {/* ── Description ─────────────────────────────────────── */}
        {job.description && (
          <>
            <Text className="text-gray-500 text-xs uppercase font-semibold tracking-widest mt-7 mb-3">
              Description
            </Text>
            <Text className="text-gray-300 text-sm leading-relaxed">
              {job.description}
            </Text>
          </>
        )}

        <View className="h-10" />
      </ScrollView>
    </>
  )
}
