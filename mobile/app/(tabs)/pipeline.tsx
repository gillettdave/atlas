import {
  View,
  Text,
  SectionList,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Alert,
} from 'react-native'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'expo-router'
import { api } from '../../services/api'
import { StageTag } from '../../components/StageTag'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import type { ApplicationJobTrack } from '../../types'

const STAGE_ORDER = [
  'new', 'applied', 'screening', 'interviewing', 'offer', 'rejected', 'archived',
]

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export default function PipelineScreen() {
  const router = useRouter()
  const queryClient = useQueryClient()

  const { data: tracks, isPending, isError, error, refetch } = useQuery({
    queryKey: ['job-tracks'],
    queryFn: () => api.getJobTracks(),
  })

  const stageMutation = useMutation({
    mutationFn: ({ trackId, stage }: { trackId: string; stage: string }) =>
      api.updateTrackStage(trackId, stage),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['job-tracks'] }),
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  function promptStageChange(track: ApplicationJobTrack) {
    const current = track.current_stage?.toLowerCase() ?? 'saved'
    Alert.alert(
      'Move to stage',
      track.job_title ?? 'This job',
      [
        ...STAGE_ORDER.filter((s) => s !== current).map((stage) => ({
          text: capitalize(stage),
          style: (['rejected', 'archived'].includes(stage) ? 'destructive' : 'default') as
            | 'destructive'
            | 'default',
          onPress: () => stageMutation.mutate({ trackId: track.id, stage }),
        })),
        { text: 'Cancel', style: 'cancel' as const },
      ]
    )
  }

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

  const allTracks: ApplicationJobTrack[] = Array.isArray(tracks) ? tracks : []

  if (allTracks.length === 0) {
    return (
      <View className="flex-1 bg-gray-950">
        <EmptyState
          icon="📋"
          title="Pipeline is empty"
          subtitle="Tap + on the Feed screen to add a job, or use Add to Pipeline on any job"
        />
      </View>
    )
  }

  const grouped = allTracks.reduce<Record<string, ApplicationJobTrack[]>>((acc, track) => {
    const stage = track.current_stage ?? 'saved'
    ;(acc[stage] ??= []).push(track)
    return acc
  }, {})

  const sections = Object.entries(grouped)
    .sort(([a], [b]) => STAGE_ORDER.indexOf(a) - STAGE_ORDER.indexOf(b))
    .map(([stage, data]) => ({ title: stage, data }))

  return (
    <View className="flex-1 bg-gray-950">
      <SectionList
        sections={sections}
        keyExtractor={(item) => String((item as ApplicationJobTrack).id)}
        contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
        stickySectionHeadersEnabled={false}
        refreshControl={
          <RefreshControl refreshing={false} onRefresh={refetch} tintColor="#818cf8" />
        }
        renderSectionHeader={({ section }) => (
          <View className="flex-row items-center gap-2 mt-5 mb-2">
            <StageTag stage={section.title} />
            <Text className="text-gray-600 text-sm">{section.data.length}</Text>
          </View>
        )}
        renderItem={({ item }) => {
          const track = item as ApplicationJobTrack
          return (
            <View className="bg-gray-900 rounded-xl mb-2 border border-gray-800 overflow-hidden">
              {/* Main tap → job detail */}
              <Pressable
                className="p-4 active:opacity-75"
                onPress={() => router.push(`/job/${track.canonical_job_id}`)}
              >
                <Text
                  className="text-gray-100 font-medium text-base"
                  numberOfLines={1}
                >
                  {track.job_title ?? 'Untitled Job'}
                </Text>
                {track.job_company_name && (
                  <Text className="text-gray-500 text-sm mt-0.5">{track.job_company_name}</Text>
                )}
                <Text className="text-gray-700 text-xs mt-2">
                  Updated {new Date(track.updated_at).toLocaleDateString()}
                </Text>
              </Pressable>

              {/* Action bar */}
              <View className="flex-row border-t border-gray-800">
                {/* Tap stage tag to change stage */}
                <Pressable
                  className="flex-1 flex-row items-center justify-center gap-2 py-2.5 active:opacity-75"
                  onPress={() => promptStageChange(track)}
                >
                  <StageTag stage={track.current_stage ?? 'saved'} />
                  <Text className="text-gray-600 text-xs">▾</Text>
                </Pressable>

                <View className="w-px bg-gray-800" />

                {/* Tap to view/generate application package */}
                <Pressable
                  className="flex-1 items-center justify-center py-2.5 active:opacity-75"
                  onPress={() => router.push(`/application/${track.canonical_job_id}`)}
                >
                  <Text className="text-gray-500 text-xs">📝 Package</Text>
                </Pressable>
              </View>
            </View>
          )
        }}
      />
    </View>
  )
}
