import {
  View,
  Text,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
  Alert,
  Switch,
} from 'react-native'
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Stack } from 'expo-router'
import { api } from '../services/api'
import type { QualificationRules } from '../types'

// ── Constants ─────────────────────────────────────────────────────────────────

const REMOTE_TYPE_OPTIONS = [
  { value: 'remote',         label: 'Remote' },
  { value: 'hybrid',         label: 'Hybrid' },
  { value: 'on_site',        label: 'On-site' },
  { value: 'remote_friendly',label: 'Remote-friendly' },
  { value: 'flexible',       label: 'Flexible' },
]

// ── Shared components ─────────────────────────────────────────────────────────

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <View className="mb-3 mt-6">
      <Text className="text-gray-500 text-xs uppercase font-semibold tracking-widest">
        {title}
      </Text>
      {subtitle && (
        <Text className="text-gray-700 text-xs mt-0.5">{subtitle}</Text>
      )}
    </View>
  )
}

// Score stepper row
function ScoreRow({
  label,
  value,
  onChange,
  editing,
}: {
  label: string
  value: number | null | undefined
  onChange: (v: number | null) => void
  editing: boolean
}) {
  const current = value ?? null
  const display = current === null ? 'Off' : String(current)

  return (
    <View className="flex-row items-center justify-between px-4 py-3 border-b border-gray-800">
      <Text className="text-gray-300 text-sm">{label}</Text>
      {editing ? (
        <View className="flex-row items-center gap-2">
          <Pressable
            className="w-7 h-7 bg-gray-800 rounded items-center justify-center active:opacity-75"
            onPress={() => {
              if (current === null) onChange(50)
              else onChange(Math.max(0, current - 5))
            }}
          >
            <Text className="text-gray-300 font-bold">−</Text>
          </Pressable>
          <Text className="text-gray-100 font-semibold w-10 text-center text-sm">
            {display}
          </Text>
          <Pressable
            className="w-7 h-7 bg-gray-800 rounded items-center justify-center active:opacity-75"
            onPress={() => {
              if (current === null) onChange(50)
              else if (current >= 100) onChange(null)
              else onChange(Math.min(100, current + 5))
            }}
          >
            <Text className="text-gray-300 font-bold">+</Text>
          </Pressable>
          {current !== null && (
            <Pressable
              className="ml-1 active:opacity-75"
              onPress={() => onChange(null)}
            >
              <Text className="text-gray-600 text-xs">✕ off</Text>
            </Pressable>
          )}
        </View>
      ) : (
        <Text className={`text-sm font-semibold ${current !== null ? 'text-indigo-400' : 'text-gray-600'}`}>
          {current !== null ? `≥ ${current}` : 'Off'}
        </Text>
      )}
    </View>
  )
}

// Multi-select chips for remote types
function RemoteTypePicker({
  value,
  onChange,
  editing,
}: {
  value: string[] | null | undefined
  onChange: (v: string[] | null) => void
  editing: boolean
}) {
  const selected = value ?? []

  function toggle(v: string) {
    if (selected.includes(v)) {
      const next = selected.filter((x) => x !== v)
      onChange(next.length ? next : null)
    } else {
      onChange([...selected, v])
    }
  }

  if (!editing && selected.length === 0) {
    return (
      <View className="px-4 py-3 border-b border-gray-800">
        <Text className="text-gray-600 text-sm italic">All types allowed</Text>
      </View>
    )
  }

  return (
    <View className="px-4 py-3 border-b border-gray-800">
      <View className="flex-row flex-wrap gap-2">
        {REMOTE_TYPE_OPTIONS.map((opt) => {
          const active = selected.includes(opt.value)
          return (
            <Pressable
              key={opt.value}
              onPress={() => editing && toggle(opt.value)}
              className={`rounded-full px-3 py-1.5 border ${
                active
                  ? 'bg-indigo-600 border-indigo-500'
                  : 'bg-gray-800 border-gray-700'
              } ${editing ? 'active:opacity-75' : ''}`}
            >
              <Text className={`text-xs font-medium ${active ? 'text-white' : 'text-gray-500'}`}>
                {opt.label}
              </Text>
            </Pressable>
          )
        })}
      </View>
      {editing && selected.length > 0 && (
        <Pressable onPress={() => onChange(null)} className="mt-2 active:opacity-75">
          <Text className="text-gray-600 text-xs">Clear (allow all)</Text>
        </Pressable>
      )}
    </View>
  )
}

// Tag list (for string[] fields)
function TagList({
  value,
  onChange,
  editing,
  placeholder,
  emptyText,
}: {
  value: string[] | null | undefined
  onChange: (v: string[] | null) => void
  editing: boolean
  placeholder: string
  emptyText: string
}) {
  const [draft, setDraft] = useState('')
  const tags = value ?? []

  function addTag() {
    const trimmed = draft.trim()
    if (!trimmed || tags.includes(trimmed)) {
      setDraft('')
      return
    }
    onChange([...tags, trimmed])
    setDraft('')
  }

  function removeTag(tag: string) {
    const next = tags.filter((t) => t !== tag)
    onChange(next.length ? next : null)
  }

  if (!editing && tags.length === 0) {
    return (
      <View className="px-4 py-3 border-b border-gray-800">
        <Text className="text-gray-600 text-sm italic">{emptyText}</Text>
      </View>
    )
  }

  return (
    <View className="px-4 py-3 border-b border-gray-800">
      {/* Existing tags */}
      {tags.length > 0 && (
        <View className="flex-row flex-wrap gap-2 mb-2">
          {tags.map((tag) => (
            <View
              key={tag}
              className="flex-row items-center bg-gray-800 rounded-full pl-3 pr-2 py-1 gap-1.5"
            >
              <Text className="text-gray-300 text-xs">{tag}</Text>
              {editing && (
                <Pressable onPress={() => removeTag(tag)} className="active:opacity-75">
                  <Text className="text-gray-500 text-xs leading-none">✕</Text>
                </Pressable>
              )}
            </View>
          ))}
        </View>
      )}

      {/* Add new tag */}
      {editing && (
        <View className="flex-row gap-2">
          <TextInput
            className="flex-1 bg-gray-800 rounded-lg px-3 py-2 text-gray-100 text-sm"
            value={draft}
            onChangeText={setDraft}
            placeholder={placeholder}
            placeholderTextColor="#4b5563"
            autoCapitalize="none"
            autoCorrect={false}
            returnKeyType="done"
            onSubmitEditing={addTag}
            blurOnSubmit={false}
          />
          <Pressable
            className="bg-indigo-600 rounded-lg px-3 py-2 items-center justify-center active:opacity-75"
            onPress={addTag}
            disabled={!draft.trim()}
          >
            <Text className="text-white text-sm font-semibold">Add</Text>
          </Pressable>
        </View>
      )}

      {tags.length === 0 && !editing && (
        <Text className="text-gray-600 text-sm italic">{emptyText}</Text>
      )}
    </View>
  )
}

// ── Main Screen ───────────────────────────────────────────────────────────────

export default function QualificationScreen() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<QualificationRules>({})

  const { data, isPending } = useQuery({
    queryKey: ['qualification-rules'],
    queryFn: () => api.getQualificationRules(),
  })

  const rules = data?.rules ?? {}

  // Sync draft when data loads or editing resets
  useEffect(() => {
    if (!editing) setDraft(rules)
  }, [data, editing])

  const saveMutation = useMutation({
    mutationFn: () => api.updateQualificationRules(draft),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['qualification-rules'] })
      setEditing(false)
      Alert.alert('Saved', 'Qualification rules updated.')
    },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  function handleCancelEdit() {
    setDraft(rules)
    setEditing(false)
  }

  function setRule<K extends keyof QualificationRules>(
    key: K,
    val: QualificationRules[K]
  ) {
    setDraft((prev) => ({ ...prev, [key]: val }))
  }

  const activeRules = editing ? draft : rules

  return (
    <>
      <Stack.Screen
        options={{
          headerShown: true,
          headerStyle: { backgroundColor: '#030712' },
          headerTintColor: '#f1f5f9',
          headerShadowVisible: false,
          headerTitle: 'Qualification Rules',
          headerBackTitle: 'Settings',
          headerRight: () =>
            editing ? (
              <View className="flex-row gap-4 pr-1">
                <Pressable onPress={handleCancelEdit} className="active:opacity-75">
                  <Text className="text-gray-400 text-base">Cancel</Text>
                </Pressable>
                <Pressable
                  onPress={() => saveMutation.mutate()}
                  disabled={saveMutation.isPending}
                  className="active:opacity-75"
                >
                  {saveMutation.isPending ? (
                    <ActivityIndicator size="small" color="#818cf8" />
                  ) : (
                    <Text className="text-indigo-400 font-semibold text-base">Save</Text>
                  )}
                </Pressable>
              </View>
            ) : (
              <Pressable
                onPress={() => {
                  setDraft({ ...rules })
                  setEditing(true)
                }}
                className="active:opacity-75 pr-1"
              >
                <Text className="text-indigo-400 text-base">Edit</Text>
              </Pressable>
            ),
        }}
      />

      <ScrollView className="flex-1 bg-gray-950" contentContainerStyle={{ padding: 20 }}>
        {isPending ? (
          <View className="py-20 items-center">
            <ActivityIndicator color="#818cf8" />
          </View>
        ) : (
          <>
            {!editing && (
              <View className="bg-gray-900 rounded-xl border border-gray-800 px-4 py-3 mb-2">
                <Text className="text-gray-400 text-sm">
                  Jobs failing these rules are excluded from digest generation (when
                  Apply Qualification is enabled). Tap <Text className="text-indigo-400">Edit</Text> to change.
                </Text>
              </View>
            )}

            {/* ── Scoring ─────────────────────────────────────────── */}
            <SectionHeader
              title="Score Filter"
              subtitle="Jobs below this ranking score are excluded"
            />
            <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
              <ScoreRow
                label="Min ranking score"
                value={activeRules.min_ranking_score}
                onChange={(v) => setRule('min_ranking_score', v)}
                editing={editing}
              />
            </View>

            {/* ── Remote types ─────────────────────────────────────── */}
            <SectionHeader
              title="Remote Types"
              subtitle="Only allow jobs matching these work arrangements"
            />
            <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
              <RemoteTypePicker
                value={activeRules.remote_types_allowed}
                onChange={(v) => setRule('remote_types_allowed', v)}
                editing={editing}
              />
            </View>

            {/* ── Must-contain ─────────────────────────────────────── */}
            <SectionHeader
              title="Must Contain (Any)"
              subtitle="Job title or description must include at least one of these phrases"
            />
            <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
              <TagList
                value={activeRules.title_or_description_must_contain_any}
                onChange={(v) => setRule('title_or_description_must_contain_any', v)}
                editing={editing}
                placeholder="e.g. engineer, product, design"
                emptyText="No keyword requirement"
              />
            </View>

            {/* ── Block if contains ─────────────────────────────────── */}
            <SectionHeader
              title="Block If Contains"
              subtitle="Reject jobs where title, company, or description includes any of these"
            />
            <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
              <TagList
                value={activeRules.block_if_text_contains_any}
                onChange={(v) => setRule('block_if_text_contains_any', v)}
                editing={editing}
                placeholder="e.g. unpaid, internship, sales"
                emptyText="No content blocklist"
              />
            </View>

            {/* ── Company blocklist ─────────────────────────────────── */}
            <SectionHeader
              title="Company Block"
              subtitle="Reject jobs from companies whose name contains any of these substrings"
            />
            <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
              <TagList
                value={activeRules.company_name_block_substrings}
                onChange={(v) => setRule('company_name_block_substrings', v)}
                editing={editing}
                placeholder="e.g. Staffing, Solutions LLC"
                emptyText="No company blocklist"
              />
            </View>

            {/* Quick actions */}
            {!editing && (
              <>
                <SectionHeader title="Actions" />
                <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
                  <Pressable
                    className="px-4 py-3.5 active:opacity-75"
                    onPress={() => {
                      setDraft({ ...rules })
                      setEditing(true)
                    }}
                  >
                    <Text className="text-indigo-400 text-sm font-semibold">Edit rules</Text>
                  </Pressable>
                </View>
              </>
            )}

            <View className="h-10" />
          </>
        )}
      </ScrollView>
    </>
  )
}
