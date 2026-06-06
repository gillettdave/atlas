import { View, Text, FlatList, Pressable, ActivityIndicator, RefreshControl } from 'react-native'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Stack, useRouter } from 'expo-router'
import { api } from '../services/api'
import { EmptyState } from '../components/EmptyState'
import type { FeedbackEvent } from '../types'

const ACTION_ICONS: Record<string, string> = {
  saved:       '🔖',
  applied:     '✅',
  skipped:     '👋',
  rejected:    '❌',
  clicked:     '👆',
  interviewed: '🎙️',
}

const ACTION_COLORS: Record<string, string> = {
  saved:       'text-indigo-400',
  applied:     'text-emerald-400',
  skipped:     'text-gray-500',
  rejected:    'text-red-400',
  clicked:     'text-blue-400',
  interviewed: 'text-yellow-400',
}

const FILTER_ACTIONS = ['all', 'saved', 'applied', 'skipped', 'rejected', 'clicked', 'interviewed']

export default function FeedbackScreen() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [activeFilter, setActiveFilter] = useState('all')

  const { data, isPending } = useQuery({
    queryKey: ['feedback', activeFilter],
    queryFn: () =>
      api.getFeedback({
        limit: 100,
        action: activeFilter === 'all' ? undefined : activeFilter,
      }),
  })

  const items: FeedbackEvent[] = data?.items ?? []

  return (
    <>
      <Stack.Screen
        options={{
          headerShown: true,
          headerStyle: { backgroundColor: '#030712' },
          headerTintColor: '#f1f5f9',
          headerShadowVisible: false,
          headerTitle: 'Feedback Log',
          headerBackTitle: 'Settings',
        }}
      />

      <View className="flex-1 bg-gray-950">
        {/* Filter chips */}
        <FlatList
          horizontal
          data={FILTER_ACTIONS}
          keyExtractor={(a) => a}
          contentContainerStyle={{ paddingHorizontal: 16, paddingVertical: 10, gap: 8 }}
          showsHorizontalScrollIndicator={false}
          renderItem={({ item: action }) => (
            <Pressable
              className={`rounded-full px-3 py-1.5 border active:opacity-75 ${
                activeFilter === action
                  ? 'bg-indigo-600 border-indigo-500'
                  : 'bg-gray-900 border-gray-800'
              }`}
              onPress={() => setActiveFilter(action)}
            >
              <Text
                className={`text-xs font-medium ${
                  activeFilter === action ? 'text-white' : 'text-gray-400'
                }`}
              >
                {action === 'all' ? 'All' : `${ACTION_ICONS[action] ?? ''} ${action}`}
              </Text>
            </Pressable>
          )}
        />

        {data && (
          <Text className="text-gray-600 text-xs px-4 pb-1">
            {data.total} total reactions
          </Text>
        )}

        {isPending ? (
          <View className="flex-1 items-center justify-center">
            <ActivityIndicator color="#818cf8" />
          </View>
        ) : items.length === 0 ? (
          <EmptyState
            icon="📊"
            title="No feedback yet"
            subtitle="React to jobs in the Feed to start building your history"
          />
        ) : (
          <FlatList
            data={items}
            keyExtractor={(item) => item.id}
            contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
            refreshControl={
              <RefreshControl
                refreshing={false}
                onRefresh={() => queryClient.invalidateQueries({ queryKey: ['feedback'] })}
                tintColor="#818cf8"
              />
            }
            renderItem={({ item }) => (
              <Pressable
                className="flex-row items-start bg-gray-900 rounded-xl p-4 mb-2 border border-gray-800 active:opacity-75"
                onPress={() => router.push(`/job/${item.job_id}`)}
              >
                <Text className="text-2xl mr-3">
                  {ACTION_ICONS[item.action] ?? '•'}
                </Text>
                <View className="flex-1">
                  <View className="flex-row items-center gap-2">
                    <Text
                      className={`text-sm font-semibold capitalize ${
                        ACTION_COLORS[item.action] ?? 'text-gray-400'
                      }`}
                    >
                      {item.action}
                    </Text>
                    {item.profile_slug && (
                      <View className="bg-gray-800 rounded px-1.5 py-0.5">
                        <Text className="text-gray-500 text-xs">{item.profile_slug}</Text>
                      </View>
                    )}
                  </View>
                  <Text className="text-gray-500 text-xs mt-0.5">
                    Job #{item.job_id}
                  </Text>
                  {item.note && (
                    <Text className="text-gray-400 text-xs mt-1 italic">{item.note}</Text>
                  )}
                  <Text className="text-gray-700 text-xs mt-1.5">
                    {new Date(item.created_at).toLocaleString()}
                  </Text>
                </View>
              </Pressable>
            )}
          />
        )}
      </View>
    </>
  )
}
