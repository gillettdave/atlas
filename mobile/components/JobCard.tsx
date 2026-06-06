import { View, Text, Pressable } from 'react-native'
import { useState } from 'react'
import { useRouter } from 'expo-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ScoreBadge } from './ScoreBadge'
import { api } from '../services/api'
import type { Job, JobReaction } from '../types'

const REACTIONS: { key: JobReaction; label: string; icon: string }[] = [
  { key: 'saved',   label: 'Save',    icon: '🔖' },
  { key: 'skipped', label: 'Skip',    icon: '👋' },
  { key: 'applied', label: 'Applied', icon: '✅' },
]

interface Props {
  job: Job
  rankPosition?: number
  /** Show inline save/skip/apply buttons. Default true. */
  showReactions?: boolean
}

export function JobCard({ job, rankPosition, showReactions = true }: Props) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [activeReaction, setActiveReaction] = useState<JobReaction | null>(null)

  const feedbackMutation = useMutation({
    mutationFn: (reaction: JobReaction) => api.submitFeedback(job.id, reaction),
    onSuccess: (_, reaction) => {
      setActiveReaction(reaction)
      // Refresh feedback log if it's open, and job list scores
      queryClient.invalidateQueries({ queryKey: ['feedback'] })
    },
  })

  // Which button is currently in-flight
  const pendingKey = feedbackMutation.isPending ? feedbackMutation.variables : null

  return (
    <View className="bg-gray-900 rounded-xl mb-3 border border-gray-800 overflow-hidden">
      {/* ── Main tap area → job detail ─────────────────────── */}
      <Pressable
        className="p-4 active:opacity-75"
        onPress={() => router.push(`/job/${job.id}`)}
      >
        <View className="flex-row items-start justify-between gap-3">
          <View className="flex-1">
            <Text
              className="text-gray-100 font-semibold text-base leading-snug"
              numberOfLines={2}
            >
              {job.title}
            </Text>
            <Text className="text-gray-400 text-sm mt-1">
              {job.company}
              {job.location ? ` · ${job.location}` : ''}
            </Text>
          </View>

          <View className="items-end gap-1.5">
            {rankPosition != null && (
              <Text className="text-gray-700 text-xs">#{rankPosition}</Text>
            )}
            <ScoreBadge score={job.ranking_score ?? job.quality_score} size="sm" />
          </View>
        </View>

        {(job.remote_type || job.source_count > 1) && (
          <View className="flex-row items-center gap-2 mt-3">
            {job.remote_type && (
              <View className="bg-gray-800 rounded px-2 py-0.5">
                <Text className="text-gray-500 text-xs capitalize">
                  {job.remote_type.replace(/_/g, ' ')}
                </Text>
              </View>
            )}
            {job.source_count > 1 && (
              <Text className="text-gray-700 text-xs">{job.source_count} sources</Text>
            )}
          </View>
        )}
      </Pressable>

      {/* ── Reaction bar ────────────────────────────────────── */}
      {showReactions && (
        <View className="flex-row border-t border-gray-800">
          {REACTIONS.map((r, i) => {
            const isActive  = activeReaction === r.key
            const isLoading = pendingKey === r.key
            return (
              <Pressable
                key={r.key}
                className={[
                  'flex-1 items-center py-2.5 active:opacity-75',
                  i < REACTIONS.length - 1 ? 'border-r border-gray-800' : '',
                  isActive ? 'bg-gray-800' : '',
                ].join(' ')}
                onPress={() => feedbackMutation.mutate(r.key)}
                disabled={feedbackMutation.isPending}
              >
                <Text className={`text-base ${isLoading ? 'opacity-40' : ''}`}>
                  {r.icon}
                </Text>
                <Text
                  className={`text-xs mt-0.5 ${
                    isActive ? 'text-indigo-400 font-semibold' : 'text-gray-600'
                  }`}
                >
                  {r.label}
                </Text>
              </Pressable>
            )
          })}
        </View>
      )}
    </View>
  )
}
