import {
  View,
  Text,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Alert,
} from 'react-native'
import { useLocalSearchParams, Stack } from 'expo-router'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../services/api'
import type { ApplicationPackage } from '../../types'

type Tab = 'resume' | 'cover_letter' | 'notes'

const TABS: { key: Tab; label: string }[] = [
  { key: 'resume',       label: 'Résumé' },
  { key: 'cover_letter', label: 'Cover Letter' },
  { key: 'notes',        label: 'Notes' },
]

function getContent(pkg: ApplicationPackage, tab: Tab): string {
  if (tab === 'resume')       return pkg.resume_markdown       ?? '—'
  if (tab === 'cover_letter') return pkg.cover_letter_markdown ?? '—'
  return pkg.strategy_notes ?? '—'
}

/** Render markdown as styled Text blocks — avoids single-Text truncation on large content. */
function MarkdownContent({ text }: { text: string }) {
  const lines = text.split('\n')
  return (
    <>
      {lines.map((line, i) => {
        if (line.startsWith('# ')) {
          return (
            <Text key={i} className="text-gray-100 text-lg font-bold mt-4 mb-1">
              {line.slice(2)}
            </Text>
          )
        }
        if (line.startsWith('## ')) {
          return (
            <Text key={i} className="text-indigo-300 text-base font-semibold mt-4 mb-1">
              {line.slice(3)}
            </Text>
          )
        }
        if (line.startsWith('### ')) {
          return (
            <Text key={i} className="text-gray-300 text-sm font-semibold mt-3 mb-0.5">
              {line.slice(4)}
            </Text>
          )
        }
        if (line.startsWith('- ') || line.startsWith('* ')) {
          return (
            <Text key={i} className="text-gray-300 text-sm leading-relaxed pl-3">
              {'•  '}{line.slice(2)}
            </Text>
          )
        }
        if (line.trim() === '') {
          return <View key={i} className="h-2" />
        }
        // Bold (**text**) inline — simple pass
        const boldParts = line.split(/\*\*(.*?)\*\*/g)
        if (boldParts.length > 1) {
          return (
            <Text key={i} className="text-gray-300 text-sm leading-relaxed">
              {boldParts.map((part, j) =>
                j % 2 === 1
                  ? <Text key={j} className="font-semibold text-gray-100">{part}</Text>
                  : part
              )}
            </Text>
          )
        }
        return (
          <Text key={i} className="text-gray-300 text-sm leading-relaxed">
            {line}
          </Text>
        )
      })}
    </>
  )
}

export default function ApplicationScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const jobId = id as string
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<Tab>('resume')

  const { data: packages, isPending } = useQuery({
    queryKey: ['packages', jobId],
    queryFn: () => api.getPackages(jobId),
  })

  const generateMutation = useMutation({
    mutationFn: () => api.generatePackage(jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['packages', jobId] }),
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const latest = packages?.[0]

  return (
    <>
      <Stack.Screen
        options={{
          headerShown: true,
          headerStyle: { backgroundColor: '#030712' },
          headerTintColor: '#f1f5f9',
          headerShadowVisible: false,
          headerTitle: 'Application Package',
          headerBackTitle: 'Back',
        }}
      />

      <View className="flex-1 bg-gray-950">
        {isPending ? (
          <View className="flex-1 items-center justify-center">
            <ActivityIndicator color="#818cf8" />
          </View>
        ) : !latest ? (
          <View className="flex-1 items-center justify-center px-8">
            <Text className="text-4xl mb-4">📝</Text>
            <Text className="text-gray-200 text-lg font-semibold text-center mb-2">
              No package yet
            </Text>
            <Text className="text-gray-500 text-sm text-center mb-6 leading-relaxed">
              Generate a tailored résumé and cover letter for this job using your career memory
            </Text>
            <Pressable
              className="bg-indigo-600 rounded-xl px-6 py-3.5 active:opacity-75"
              onPress={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
            >
              {generateMutation.isPending ? (
                <View className="flex-row items-center gap-2">
                  <ActivityIndicator size="small" color="white" />
                  <Text className="text-white font-semibold">Generating…</Text>
                </View>
              ) : (
                <Text className="text-white font-semibold">Generate Package</Text>
              )}
            </Pressable>
          </View>
        ) : (
          <>
            {/* Tab bar */}
            <View className="flex-row items-center border-b border-gray-800 px-4">
              {TABS.map((tab) => (
                <Pressable
                  key={tab.key}
                  className={`mr-5 py-3 ${
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
              <View className="flex-1" />
              <Pressable
                className="py-3 active:opacity-75"
                onPress={() => generateMutation.mutate()}
                disabled={generateMutation.isPending}
              >
                <Text className="text-indigo-400 text-sm">
                  {generateMutation.isPending ? 'Generating…' : '↻ Regenerate'}
                </Text>
              </Pressable>
            </View>

            {/* Content */}
            <ScrollView
              className="flex-1"
              contentContainerStyle={{ padding: 20, paddingBottom: 80 }}
              nestedScrollEnabled
            >
              <View className="bg-gray-900 rounded-xl p-4 border border-gray-800">
                <MarkdownContent text={getContent(latest, activeTab)} />
              </View>
              <Text className="text-gray-700 text-xs mt-3 text-center">
                v{latest.version} · {new Date(latest.created_at).toLocaleString()}
              </Text>
            </ScrollView>
          </>
        )}
      </View>
    </>
  )
}
