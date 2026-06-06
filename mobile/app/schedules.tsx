import {
  View,
  Text,
  FlatList,
  Pressable,
  ActivityIndicator,
  Modal,
  ScrollView,
  TextInput,
  Switch,
  Alert,
  RefreshControl,
} from 'react-native'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Stack } from 'expo-router'
import { api } from '../services/api'
import { EmptyState } from '../components/EmptyState'
import type { Schedule, ScheduleCreate, ScheduleCadence, ScheduleChannel } from '../types'

// ── Helpers ───────────────────────────────────────────────────────────────────

const CADENCE_OPTIONS: { value: ScheduleCadence; label: string }[] = [
  { value: 'daily',           label: 'Daily' },
  { value: 'hourly',          label: 'Hourly' },
  { value: 'every_n_minutes', label: 'Every N min' },
  { value: 'cron',            label: 'Cron' },
]

const CHANNEL_OPTIONS: { value: ScheduleChannel; label: string; icon: string }[] = [
  { value: 'slack',    label: 'Slack',    icon: '💬' },
  { value: 'email',    label: 'Email',    icon: '📧' },
  { value: 'csv_only', label: 'CSV',      icon: '📄' },
  { value: 'none',     label: 'None',     icon: '🔕' },
]

const STATUS_COLOR: Record<string, string> = {
  ok:      'text-emerald-400',
  error:   'text-red-400',
  skipped: 'text-gray-500',
}

function formatCadence(s: Schedule): string {
  const pad = (n: number | null) => String(n ?? 0).padStart(2, '0')
  if (s.cadence === 'daily')
    return `Daily at ${pad(s.hour_utc)}:${pad(s.minute_utc)} UTC`
  if (s.cadence === 'hourly')
    return `Hourly at :${pad(s.minute_utc)}`
  if (s.cadence === 'every_n_minutes')
    return `Every ${s.interval_minutes ?? '?'} min`
  if (s.cadence === 'cron')
    return `Cron: ${s.cron_expression ?? '?'}`
  return s.cadence
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

// ── Schedule Form ─────────────────────────────────────────────────────────────

interface ScheduleFormState {
  name: string
  cadence: ScheduleCadence
  hour_utc: string
  minute_utc: string
  interval_minutes: string
  cron_expression: string
  channel: ScheduleChannel
  webhook_url: string
  recipients: string   // comma-separated
  include_hidden_gems: boolean
  is_active: boolean
}

const DEFAULT_FORM: ScheduleFormState = {
  name: '',
  cadence: 'daily',
  hour_utc: '9',
  minute_utc: '0',
  interval_minutes: '60',
  cron_expression: '0 9 * * 1-5',
  channel: 'none',
  webhook_url: '',
  recipients: '',
  include_hidden_gems: true,
  is_active: true,
}

function scheduleToForm(s: Schedule): ScheduleFormState {
  return {
    name: s.name,
    cadence: s.cadence,
    hour_utc: String(s.hour_utc ?? 9),
    minute_utc: String(s.minute_utc ?? 0),
    interval_minutes: String(s.interval_minutes ?? 60),
    cron_expression: s.cron_expression ?? '0 9 * * 1-5',
    channel: s.channel,
    webhook_url: s.webhook_url ?? '',
    recipients: (s.recipients ?? []).join(', '),
    include_hidden_gems: s.include_hidden_gems,
    is_active: s.is_active,
  }
}

function formToPayload(f: ScheduleFormState): ScheduleCreate {
  const payload: ScheduleCreate = {
    name: f.name.trim(),
    cadence: f.cadence,
    channel: f.channel,
    include_hidden_gems: f.include_hidden_gems,
    is_active: f.is_active,
  }
  if (f.cadence === 'daily') {
    payload.hour_utc = parseInt(f.hour_utc, 10) || 9
    payload.minute_utc = parseInt(f.minute_utc, 10) || 0
  } else if (f.cadence === 'hourly') {
    payload.minute_utc = parseInt(f.minute_utc, 10) || 0
  } else if (f.cadence === 'every_n_minutes') {
    payload.interval_minutes = parseInt(f.interval_minutes, 10) || 60
  } else if (f.cadence === 'cron') {
    payload.cron_expression = f.cron_expression.trim()
  }
  if (f.channel === 'slack' && f.webhook_url.trim()) {
    payload.webhook_url = f.webhook_url.trim()
  }
  if (f.channel === 'email' && f.recipients.trim()) {
    payload.recipients = f.recipients.split(',').map(r => r.trim()).filter(Boolean)
  }
  return payload
}

// ── Segmented picker ──────────────────────────────────────────────────────────

function SegPicker<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <View className="flex-row bg-gray-800 rounded-xl p-0.5 gap-0.5">
      {options.map((opt) => (
        <Pressable
          key={opt.value}
          className={`flex-1 py-2 rounded-lg items-center active:opacity-75 ${
            value === opt.value ? 'bg-gray-600' : ''
          }`}
          onPress={() => onChange(opt.value)}
        >
          <Text
            className={`text-xs font-medium ${
              value === opt.value ? 'text-gray-100' : 'text-gray-500'
            }`}
            numberOfLines={1}
          >
            {opt.label}
          </Text>
        </Pressable>
      ))}
    </View>
  )
}

// ── Form field ────────────────────────────────────────────────────────────────

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <View className="mb-4">
      <Text className="text-gray-500 text-xs uppercase font-semibold tracking-wider mb-1.5">
        {label}
      </Text>
      {children}
    </View>
  )
}

// ── Schedule Form Modal ───────────────────────────────────────────────────────

function ScheduleFormModal({
  visible,
  editing,
  onClose,
}: {
  visible: boolean
  editing: Schedule | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<ScheduleFormState>(
    editing ? scheduleToForm(editing) : DEFAULT_FORM
  )

  // Reset form when modal opens with different editing target
  const reset = (s: Schedule | null) =>
    setForm(s ? scheduleToForm(s) : DEFAULT_FORM)

  const createMutation = useMutation({
    mutationFn: () => api.createSchedule(formToPayload(form)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] })
      onClose()
    },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const updateMutation = useMutation({
    mutationFn: () => api.updateSchedule(editing!.id, formToPayload(form)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] })
      onClose()
    },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteSchedule(editing!.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] })
      onClose()
    },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  function handleDelete() {
    Alert.alert(
      'Delete schedule?',
      `"${editing?.name}" will be removed permanently.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: () => deleteMutation.mutate(),
        },
      ]
    )
  }

  const isPending =
    createMutation.isPending || updateMutation.isPending || deleteMutation.isPending

  function set<K extends keyof ScheduleFormState>(key: K, val: ScheduleFormState[K]) {
    setForm((prev) => ({ ...prev, [key]: val }))
  }

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
      onShow={() => reset(editing)}
    >
      <View className="flex-1 bg-gray-950">
        {/* Header */}
        <View className="flex-row items-center justify-between px-5 pt-5 pb-3 border-b border-gray-800">
          <Pressable onPress={onClose} className="active:opacity-75">
            <Text className="text-gray-400 text-base">Cancel</Text>
          </Pressable>
          <Text className="text-gray-100 font-semibold text-base">
            {editing ? 'Edit Schedule' : 'New Schedule'}
          </Text>
          <Pressable
            onPress={() =>
              editing ? updateMutation.mutate() : createMutation.mutate()
            }
            disabled={isPending || !form.name.trim()}
            className="active:opacity-75"
          >
            {isPending ? (
              <ActivityIndicator size="small" color="#818cf8" />
            ) : (
              <Text
                className={`font-semibold text-base ${
                  form.name.trim() ? 'text-indigo-400' : 'text-gray-600'
                }`}
              >
                {editing ? 'Save' : 'Create'}
              </Text>
            )}
          </Pressable>
        </View>

        <ScrollView
          className="flex-1"
          contentContainerStyle={{ padding: 20 }}
          keyboardShouldPersistTaps="handled"
        >
          {/* Name */}
          <Field label="Name">
            <TextInput
              className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 text-gray-100 text-sm"
              value={form.name}
              onChangeText={(v) => set('name', v)}
              placeholder="Daily digest"
              placeholderTextColor="#4b5563"
              autoFocus={!editing}
            />
          </Field>

          {/* Cadence */}
          <Field label="Cadence">
            <SegPicker
              options={CADENCE_OPTIONS}
              value={form.cadence}
              onChange={(v) => set('cadence', v)}
            />
          </Field>

          {/* Cadence-specific fields */}
          {form.cadence === 'daily' && (
            <View className="flex-row gap-3 mb-4">
              <View className="flex-1">
                <Text className="text-gray-500 text-xs uppercase font-semibold tracking-wider mb-1.5">
                  Hour (UTC, 0–23)
                </Text>
                <TextInput
                  className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 text-gray-100 text-sm"
                  value={form.hour_utc}
                  onChangeText={(v) => set('hour_utc', v)}
                  keyboardType="number-pad"
                  maxLength={2}
                />
              </View>
              <View className="flex-1">
                <Text className="text-gray-500 text-xs uppercase font-semibold tracking-wider mb-1.5">
                  Minute (0–59)
                </Text>
                <TextInput
                  className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 text-gray-100 text-sm"
                  value={form.minute_utc}
                  onChangeText={(v) => set('minute_utc', v)}
                  keyboardType="number-pad"
                  maxLength={2}
                />
              </View>
            </View>
          )}

          {form.cadence === 'hourly' && (
            <Field label="Minute past the hour (0–59)">
              <TextInput
                className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 text-gray-100 text-sm"
                value={form.minute_utc}
                onChangeText={(v) => set('minute_utc', v)}
                keyboardType="number-pad"
                maxLength={2}
              />
            </Field>
          )}

          {form.cadence === 'every_n_minutes' && (
            <Field label="Interval (minutes, 1–1440)">
              <TextInput
                className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 text-gray-100 text-sm"
                value={form.interval_minutes}
                onChangeText={(v) => set('interval_minutes', v)}
                keyboardType="number-pad"
                maxLength={4}
              />
            </Field>
          )}

          {form.cadence === 'cron' && (
            <Field label="Cron expression (UTC, 5-field)">
              <TextInput
                className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 text-gray-100 text-sm font-mono"
                value={form.cron_expression}
                onChangeText={(v) => set('cron_expression', v)}
                placeholder="0 9 * * 1-5"
                placeholderTextColor="#4b5563"
                autoCapitalize="none"
                autoCorrect={false}
              />
            </Field>
          )}

          {/* Channel */}
          <Field label="Delivery channel">
            <SegPicker
              options={CHANNEL_OPTIONS}
              value={form.channel}
              onChange={(v) => set('channel', v)}
            />
          </Field>

          {form.channel === 'slack' && (
            <Field label="Webhook URL (optional — overrides env var)">
              <TextInput
                className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 text-gray-100 text-sm"
                value={form.webhook_url}
                onChangeText={(v) => set('webhook_url', v)}
                placeholder="https://hooks.slack.com/services/..."
                placeholderTextColor="#4b5563"
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="url"
              />
            </Field>
          )}

          {form.channel === 'email' && (
            <Field label="Recipients (comma-separated emails)">
              <TextInput
                className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 text-gray-100 text-sm"
                value={form.recipients}
                onChangeText={(v) => set('recipients', v)}
                placeholder="you@example.com, other@example.com"
                placeholderTextColor="#4b5563"
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="email-address"
                multiline
              />
            </Field>
          )}

          {/* Toggles */}
          <View className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden mb-4">
            <View className="flex-row items-center justify-between px-4 py-3.5 border-b border-gray-800">
              <Text className="text-gray-300 text-sm">Include hidden gems</Text>
              <Switch
                value={form.include_hidden_gems}
                onValueChange={(v) => set('include_hidden_gems', v)}
                trackColor={{ false: '#374151', true: '#4f46e5' }}
                thumbColor="#f1f5f9"
              />
            </View>
            <View className="flex-row items-center justify-between px-4 py-3.5">
              <Text className="text-gray-300 text-sm">Active</Text>
              <Switch
                value={form.is_active}
                onValueChange={(v) => set('is_active', v)}
                trackColor={{ false: '#374151', true: '#4f46e5' }}
                thumbColor="#f1f5f9"
              />
            </View>
          </View>

          {/* Delete button (edit only) */}
          {editing && (
            <Pressable
              className="bg-red-950 border border-red-900 rounded-xl py-3.5 items-center active:opacity-75 mt-2"
              onPress={handleDelete}
              disabled={isPending}
            >
              <Text className="text-red-400 font-semibold">Delete Schedule</Text>
            </Pressable>
          )}
        </ScrollView>
      </View>
    </Modal>
  )
}

// ── Schedule Card ─────────────────────────────────────────────────────────────

function ScheduleCard({
  schedule,
  onEdit,
}: {
  schedule: Schedule
  onEdit: (s: Schedule) => void
}) {
  const queryClient = useQueryClient()

  const runMutation = useMutation({
    mutationFn: () => api.runScheduleNow(schedule.id),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] })
      const msg = result.delivered
        ? `Delivered via ${result.channel}`
        : result.detail ?? 'No delivery (channel: none or csv_only)'
      Alert.alert(result.status === 'ok' ? 'Run complete ✓' : 'Run failed', msg)
    },
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const toggleMutation = useMutation({
    mutationFn: (active: boolean) =>
      api.updateSchedule(schedule.id, { is_active: active }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['schedules'] }),
    onError: (e: Error) => Alert.alert('Error', e.message),
  })

  const channelInfo = CHANNEL_OPTIONS.find((c) => c.value === schedule.channel)

  return (
    <View className="bg-gray-900 rounded-xl border border-gray-800 mb-3 overflow-hidden">
      {/* Main info */}
      <Pressable
        className="p-4 active:opacity-75"
        onPress={() => onEdit(schedule)}
      >
        <View className="flex-row items-start justify-between">
          <View className="flex-1 mr-3">
            <Text className="text-gray-100 font-semibold text-base" numberOfLines={1}>
              {schedule.name}
            </Text>
            <Text className="text-gray-500 text-xs mt-0.5">{formatCadence(schedule)}</Text>
          </View>
          <View className="flex-row items-center gap-2">
            {channelInfo && (
              <View className="bg-gray-800 rounded px-2 py-0.5">
                <Text className="text-gray-400 text-xs">
                  {channelInfo.icon} {channelInfo.label}
                </Text>
              </View>
            )}
            <Text className="text-gray-600 text-xs">›</Text>
          </View>
        </View>

        {/* Last/next run */}
        <View className="flex-row gap-4 mt-2.5">
          <View>
            <Text className="text-gray-700 text-xs">Last run</Text>
            <Text
              className={`text-xs mt-0.5 ${
                STATUS_COLOR[schedule.last_status ?? ''] ?? 'text-gray-600'
              }`}
            >
              {schedule.last_run_at ? formatDate(schedule.last_run_at) : '—'}
              {schedule.last_status ? ` · ${schedule.last_status}` : ''}
            </Text>
          </View>
          <View>
            <Text className="text-gray-700 text-xs">Next run</Text>
            <Text className="text-gray-600 text-xs mt-0.5">
              {formatDate(schedule.next_run_at)}
            </Text>
          </View>
        </View>

        {schedule.last_error && (
          <Text className="text-red-400 text-xs mt-1.5" numberOfLines={2}>
            {schedule.last_error}
          </Text>
        )}
      </Pressable>

      {/* Action bar */}
      <View className="flex-row border-t border-gray-800">
        <View className="flex-1 flex-row items-center justify-between px-4 py-2.5">
          <Text className="text-gray-500 text-xs">
            {schedule.is_active ? 'Active' : 'Paused'}
          </Text>
          <Switch
            value={schedule.is_active}
            onValueChange={(v) => toggleMutation.mutate(v)}
            trackColor={{ false: '#374151', true: '#4f46e5' }}
            thumbColor="#f1f5f9"
          />
        </View>

        <View className="w-px bg-gray-800" />

        <Pressable
          className="flex-1 items-center justify-center py-2.5 active:opacity-75"
          onPress={() => runMutation.mutate()}
          disabled={runMutation.isPending}
        >
          {runMutation.isPending ? (
            <ActivityIndicator size="small" color="#818cf8" />
          ) : (
            <Text className="text-indigo-400 text-xs font-semibold">▶ Run Now</Text>
          )}
        </Pressable>
      </View>
    </View>
  )
}

// ── Main Screen ───────────────────────────────────────────────────────────────

export default function SchedulesScreen() {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<Schedule | null>(null)

  const { data: schedules, isPending, refetch } = useQuery({
    queryKey: ['schedules'],
    queryFn: () => api.getSchedules(),
  })

  const items = schedules ?? []

  function openCreate() {
    setEditing(null)
    setShowForm(true)
  }

  function openEdit(s: Schedule) {
    setEditing(s)
    setShowForm(true)
  }

  return (
    <>
      <Stack.Screen
        options={{
          headerShown: true,
          headerStyle: { backgroundColor: '#030712' },
          headerTintColor: '#f1f5f9',
          headerShadowVisible: false,
          headerTitle: 'Schedules',
          headerBackTitle: 'Settings',
          headerRight: () => (
            <Pressable onPress={openCreate} className="active:opacity-75 pr-1">
              <Text className="text-indigo-400 font-bold text-xl leading-none">+</Text>
            </Pressable>
          ),
        }}
      />

      <View className="flex-1 bg-gray-950">
        {isPending ? (
          <View className="flex-1 items-center justify-center">
            <ActivityIndicator color="#818cf8" />
          </View>
        ) : items.length === 0 ? (
          <EmptyState
            icon="⏰"
            title="No schedules yet"
            subtitle="Tap + to create a delivery schedule for your digests"
          />
        ) : (
          <FlatList
            data={items}
            keyExtractor={(s) => s.id}
            contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
            refreshControl={
              <RefreshControl
                refreshing={false}
                onRefresh={() => queryClient.invalidateQueries({ queryKey: ['schedules'] })}
                tintColor="#818cf8"
              />
            }
            renderItem={({ item }) => (
              <ScheduleCard schedule={item} onEdit={openEdit} />
            )}
          />
        )}
      </View>

      <ScheduleFormModal
        visible={showForm}
        editing={editing}
        onClose={() => setShowForm(false)}
      />
    </>
  )
}
