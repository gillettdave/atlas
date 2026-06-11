import {
  View,
  Text,
  ScrollView,
  TextInput,
  Pressable,
  ActivityIndicator,
  Alert,
  Modal,
} from 'react-native'
import { useLocalSearchParams, Stack } from 'expo-router'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import * as FileSystem from 'expo-file-system'
import * as Sharing from 'expo-sharing'
import * as MailComposer from 'expo-mail-composer'
import { api } from '../../services/api'
import type { ApplicationPackage } from '../../types'

type Tab = 'resume' | 'cover_letter' | 'notes'

const TABS: { key: Tab; label: string }[] = [
  { key: 'resume',       label: 'Résumé' },
  { key: 'cover_letter', label: 'Cover Letter' },
  { key: 'notes',        label: 'Notes' },
]

function getContent(pkg: ApplicationPackage, tab: Tab): string {
  if (tab === 'resume')       return pkg.resume_markdown       ?? ''
  if (tab === 'cover_letter') return pkg.cover_letter_markdown ?? ''
  return pkg.strategy_notes ?? ''
}

function MarkdownContent({ text }: { text: string }) {
  const lines = text.split('\n')
  return (
    <>
      {lines.map((line, i) => {
        if (line.startsWith('# ')) {
          return <Text key={i} className="text-gray-100 text-lg font-bold mt-4 mb-1">{line.slice(2)}</Text>
        }
        if (line.startsWith('## ')) {
          return <Text key={i} className="text-indigo-300 text-base font-semibold mt-4 mb-1">{line.slice(3)}</Text>
        }
        if (line.startsWith('### ')) {
          return <Text key={i} className="text-gray-300 text-sm font-semibold mt-3 mb-0.5">{line.slice(4)}</Text>
        }
        if (line.startsWith('- ') || line.startsWith('* ')) {
          return <Text key={i} className="text-gray-300 text-sm leading-relaxed pl-3">{'•  '}{line.slice(2)}</Text>
        }
        if (line.trim() === '') {
          return <View key={i} className="h-2" />
        }
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
        return <Text key={i} className="text-gray-300 text-sm leading-relaxed">{line}</Text>
      })}
    </>
  )
}

export default function ApplicationScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const jobId = id as string
  const queryClient = useQueryClient()

  const [activeTab, setActiveTab] = useState<Tab>('resume')
  const [editing, setEditing] = useState(false)
  const [draftResume, setDraftResume] = useState('')
  const [draftCover, setDraftCover] = useState('')
  const [draftNotes, setDraftNotes] = useState('')
  const [showDownload, setShowDownload] = useState(false)
  const [downloading, setDownloading] = useState(false)

  const { data: packages, isPending } = useQuery({
    queryKey: ['packages', jobId],
    queryFn: () => api.getPackages(jobId),
  })

  const latest = packages?.[0]

  const { data: job } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.getJob(jobId),
  })

  // Sync drafts when package loads or changes
  useEffect(() => {
    if (latest) {
      setDraftResume(latest.resume_markdown ?? '')
      setDraftCover(latest.cover_letter_markdown ?? '')
      setDraftNotes(latest.strategy_notes ?? '')
    }
  }, [latest?.id])

  const generateMutation = useMutation({
    mutationFn: () => api.generatePackage(jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['packages', jobId] }),
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const saveMutation = useMutation({
    mutationFn: () => api.savePackage(jobId, {
      resume_markdown: draftResume,
      cover_letter_markdown: draftCover,
      strategy_notes: draftNotes,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['packages', jobId] })
      setEditing(false)
      Alert.alert('Saved ✓', 'Your edits have been saved as a new version.')
    },
    onError: (e: Error) => Alert.alert('Save failed', e.message),
  })

  function cancelEdit() {
    if (latest) {
      setDraftResume(latest.resume_markdown ?? '')
      setDraftCover(latest.cover_letter_markdown ?? '')
      setDraftNotes(latest.strategy_notes ?? '')
    }
    setEditing(false)
  }

  function getDraftForTab(tab: Tab): string {
    if (tab === 'resume')       return draftResume
    if (tab === 'cover_letter') return draftCover
    return draftNotes
  }

  function setDraftForTab(tab: Tab, value: string) {
    if (tab === 'resume')       setDraftResume(value)
    else if (tab === 'cover_letter') setDraftCover(value)
    else setDraftNotes(value)
  }

  async function handleEmail() {
    if (!latest) return
    const available = await MailComposer.isAvailableAsync()
    if (!available) {
      Alert.alert('Mail not available', 'No mail app is configured on this device.')
      return
    }
    const jobTitle = job?.title ?? 'Job'
    const company  = job?.company_name ?? ''
    const applyUrl = job?.canonical_apply_url ?? job?.apply_url ?? ''
    const parts: string[] = []
    if (applyUrl) { parts.push(`Job posting: ${applyUrl}`, '') }
    parts.push('=== RÉSUMÉ ===', latest.resume_markdown ?? '', '', '=== COVER LETTER ===', latest.cover_letter_markdown ?? '')
    await MailComposer.composeAsync({
      subject: `Application: ${jobTitle}${company ? ` at ${company}` : ''}`,
      body: parts.join('\n'),
    })
  }

  async function handleDownloadTxt() {
    if (!latest) return
    setDownloading(true)
    try {
      const content = [
        '=== RÉSUMÉ ===',
        latest.resume_markdown ?? '',
        '',
        '=== COVER LETTER ===',
        latest.cover_letter_markdown ?? '',
      ].join('\n')
      const path = `${FileSystem.cacheDirectory}application_package.txt`
      await FileSystem.writeAsStringAsync(path, content, { encoding: FileSystem.EncodingType.UTF8 })
      await Sharing.shareAsync(path, { mimeType: 'text/plain', dialogTitle: 'Save Application Package' })
    } catch (e: unknown) {
      Alert.alert('Export failed', e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setDownloading(false)
      setShowDownload(false)
    }
  }

  async function handleDownloadDocx(part: 'resume' | 'cover-letter' | 'zip') {
    if (!latest) return
    setDownloading(true)
    try {
      const res = await api.downloadPackageDocx(jobId, latest.id, part)
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      const buffer = await res.arrayBuffer()
      const bytes = new Uint8Array(buffer)
      let binary = ''
      for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i])
      const base64 = btoa(binary)
      const ext = part === 'zip' ? 'zip' : 'docx'
      const mime = part === 'zip' ? 'application/zip' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      const filename = part === 'zip' ? 'application_package.zip' : `${part}.docx`
      const path = `${FileSystem.cacheDirectory}${filename}`
      await FileSystem.writeAsStringAsync(path, base64, { encoding: FileSystem.EncodingType.Base64 })
      await Sharing.shareAsync(path, { mimeType: mime, dialogTitle: 'Save Document' })
    } catch (e: unknown) {
      Alert.alert('Download failed', e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setDownloading(false)
      setShowDownload(false)
    }
  }

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
            <Text className="text-gray-200 text-lg font-semibold text-center mb-2">No package yet</Text>
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
                  className={`mr-5 py-3 ${activeTab === tab.key ? 'border-b-2 border-indigo-500' : ''}`}
                  onPress={() => setActiveTab(tab.key)}
                >
                  <Text className={activeTab === tab.key ? 'text-indigo-400 font-semibold text-sm' : 'text-gray-600 text-sm'}>
                    {tab.label}
                  </Text>
                </Pressable>
              ))}
              <View className="flex-1" />
              {editing ? (
                <View className="flex-row gap-3 py-2">
                  <Pressable onPress={cancelEdit} className="active:opacity-60">
                    <Text className="text-gray-500 text-sm">Cancel</Text>
                  </Pressable>
                  <Pressable
                    onPress={() => saveMutation.mutate()}
                    disabled={saveMutation.isPending}
                    className="active:opacity-60"
                  >
                    {saveMutation.isPending
                      ? <ActivityIndicator size="small" color="#818cf8" />
                      : <Text className="text-indigo-400 text-sm font-semibold">Save</Text>
                    }
                  </Pressable>
                </View>
              ) : (
                <Pressable
                  className="py-3 active:opacity-75"
                  onPress={() => generateMutation.mutate()}
                  disabled={generateMutation.isPending}
                >
                  <Text className="text-indigo-400 text-sm">
                    {generateMutation.isPending ? 'Generating…' : '↻ Regenerate'}
                  </Text>
                </Pressable>
              )}
            </View>

            {/* Action bar */}
            {!editing && (
              <View className="flex-row items-center gap-2 px-4 py-2 border-b border-gray-800">
                <Pressable
                  className="flex-row items-center gap-1.5 bg-gray-800 rounded-lg px-3 py-1.5 active:opacity-70"
                  onPress={() => setEditing(true)}
                >
                  <Text className="text-gray-300 text-xs">✏️ Edit</Text>
                </Pressable>
                <Pressable
                  className="flex-row items-center gap-1.5 bg-gray-800 rounded-lg px-3 py-1.5 active:opacity-70"
                  onPress={handleEmail}
                >
                  <Text className="text-gray-300 text-xs">📧 Email</Text>
                </Pressable>
                <Pressable
                  className="flex-row items-center gap-1.5 bg-gray-800 rounded-lg px-3 py-1.5 active:opacity-70"
                  onPress={() => setShowDownload(true)}
                  disabled={downloading}
                >
                  {downloading
                    ? <ActivityIndicator size="small" color="#9ca3af" />
                    : <Text className="text-gray-300 text-xs">⬇ Download</Text>
                  }
                </Pressable>
              </View>
            )}

            {/* Content */}
            {editing ? (
              <TextInput
                className="flex-1 text-gray-300 text-sm leading-relaxed p-5 font-mono"
                multiline
                value={getDraftForTab(activeTab)}
                onChangeText={(v) => setDraftForTab(activeTab, v)}
                autoCapitalize="none"
                autoCorrect={false}
                scrollEnabled
                textAlignVertical="top"
              />
            ) : (
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
            )}

            {/* Download format picker */}
            <Modal
              visible={showDownload}
              transparent
              animationType="fade"
              onRequestClose={() => setShowDownload(false)}
            >
              <Pressable
                className="flex-1 bg-black/60 justify-end"
                onPress={() => setShowDownload(false)}
              >
                <Pressable onPress={() => {}} className="bg-gray-900 rounded-t-2xl pb-10">
                  <View className="flex-row items-center justify-between px-5 pt-5 pb-4 border-b border-gray-800">
                    <Text className="text-gray-200 font-semibold text-base">Download As</Text>
                    <Pressable onPress={() => setShowDownload(false)} className="active:opacity-60">
                      <Text className="text-gray-500 text-sm">✕</Text>
                    </Pressable>
                  </View>

                  {[
                    { label: 'Résumé (.docx)', sub: 'Word document — open in Word or Google Docs', onPress: () => handleDownloadDocx('resume') },
                    { label: 'Cover Letter (.docx)', sub: 'Word document — open in Word or Google Docs', onPress: () => handleDownloadDocx('cover-letter') },
                    { label: 'Both (.zip)', sub: 'ZIP with résumé + cover letter + notes as Word files', onPress: () => handleDownloadDocx('zip') },
                    { label: 'Plain Text (.txt)', sub: 'Résumé + cover letter in a single text file', onPress: handleDownloadTxt },
                  ].map((item, i, arr) => (
                    <Pressable
                      key={item.label}
                      className={`px-5 py-4 active:opacity-70 ${i < arr.length - 1 ? 'border-b border-gray-800' : ''}`}
                      onPress={item.onPress}
                    >
                      <Text className="text-gray-200 text-sm font-medium">{item.label}</Text>
                      <Text className="text-gray-500 text-xs mt-0.5">{item.sub}</Text>
                    </Pressable>
                  ))}
                </Pressable>
              </Pressable>
            </Modal>
          </>
        )}
      </View>
    </>
  )
}
