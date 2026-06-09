/**
 * Onboarding flow — shown on first launch when no profile is set.
 *
 * Step 1: Role picker (8 role cards)
 * Step 2: Work preference (Remote / Hybrid / Open to local)
 * Step 3: Location (optional — use GPS or skip)
 * Step 4: "Finding your jobs…" — calls from-template then find-jobs, then navigates to Feed
 */
import {
  View,
  Text,
  Pressable,
  ScrollView,
  ActivityIndicator,
  Alert,
} from 'react-native'
import { useState, useCallback } from 'react'
import { useRouter } from 'expo-router'
import { useConfigStore } from '../stores/config'
import { api } from '../services/api'

// ─── Role definitions ──────────────────────────────────────────────────────

const ROLES = [
  { slug: 'community_manager', emoji: '💬', label: 'Community Manager', sub: 'Build & grow communities' },
  { slug: 'devrel',            emoji: '🧑‍💻', label: 'Developer Relations', sub: 'Advocacy, docs & SDKs' },
  { slug: 'growth',            emoji: '📈', label: 'Growth',               sub: 'Acquisition & retention' },
  { slug: 'marketing_manager', emoji: '📣', label: 'Marketing Manager',    sub: 'Brand, campaigns & content' },
  { slug: 'customer_success',  emoji: '🤝', label: 'Customer Success',     sub: 'CSM, onboarding & retention' },
  { slug: 'operations',        emoji: '⚙️', label: 'Operations',           sub: 'Process, tooling & systems' },
  { slug: 'product_manager',   emoji: '🗺️', label: 'Product Manager',      sub: 'Roadmap & discovery' },
  { slug: 'sales',             emoji: '💰', label: 'Sales / BD',           sub: 'Pipeline & revenue' },
] as const

type RoleSlug = typeof ROLES[number]['slug']
type RemotePref = 'remote' | 'hybrid' | 'onsite'

const REMOTE_OPTIONS: { value: RemotePref; label: string; sub: string }[] = [
  { value: 'remote',  label: '🌍 Remote only',       sub: 'I want fully remote positions' },
  { value: 'hybrid',  label: '🏢 Open to hybrid',    sub: 'Mix of office & remote is fine' },
  { value: 'onsite',  label: '📍 Open to on-site',   sub: 'Location-based roles are OK' },
]

// ─── Sub-components ────────────────────────────────────────────────────────

function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <View className="flex-row gap-2 justify-center mb-8">
      {Array.from({ length: total }).map((_, i) => (
        <View
          key={i}
          className={`h-1.5 rounded-full ${i === current ? 'w-6 bg-indigo-400' : 'w-1.5 bg-gray-700'}`}
        />
      ))}
    </View>
  )
}

// ─── Main component ────────────────────────────────────────────────────────

export default function OnboardingScreen() {
  const router = useRouter()
  const { setActiveProfile, setOnboardingDismissed } = useConfigStore()

  const [step, setStep] = useState(0)
  const [selectedRole, setSelectedRole] = useState<RoleSlug | null>(null)
  const [remotePref, setRemotePref] = useState<RemotePref>('remote')
  const [loading, setLoading] = useState(false)
  const [statusText, setStatusText] = useState('Setting up your profile…')

  const skipOnboarding = useCallback(() => {
    setOnboardingDismissed(true)
    router.replace('/(tabs)')
  }, [router, setOnboardingDismissed])

  // ── Step 0: Role picker ──────────────────────────────────────────────────

  const renderRolePicker = () => (
    <View className="flex-1">
      <Text className="text-white text-2xl font-bold mb-2">What type of role are you looking for?</Text>
      <Text className="text-gray-400 text-sm mb-6">We'll tune your job feed to match.</Text>
      <ScrollView showsVerticalScrollIndicator={false} className="flex-1">
        <View className="gap-3 pb-6">
          {ROLES.map((role) => {
            const selected = selectedRole === role.slug
            return (
              <Pressable
                key={role.slug}
                onPress={() => setSelectedRole(role.slug)}
                className={`flex-row items-center gap-4 px-4 py-4 rounded-xl border ${
                  selected
                    ? 'bg-indigo-900/40 border-indigo-500'
                    : 'bg-gray-900 border-gray-800'
                }`}
              >
                <Text className="text-2xl">{role.emoji}</Text>
                <View className="flex-1">
                  <Text className={`font-semibold text-sm ${selected ? 'text-indigo-300' : 'text-white'}`}>
                    {role.label}
                  </Text>
                  <Text className="text-gray-500 text-xs mt-0.5">{role.sub}</Text>
                </View>
                {selected && (
                  <View className="w-5 h-5 rounded-full bg-indigo-500 items-center justify-center">
                    <Text className="text-white text-xs font-bold">✓</Text>
                  </View>
                )}
              </Pressable>
            )
          })}
        </View>
      </ScrollView>
      <View className="pt-4 gap-3">
        <Pressable
          onPress={() => selectedRole && setStep(1)}
          disabled={!selectedRole}
          className={`py-4 rounded-xl items-center ${
            selectedRole ? 'bg-indigo-600 active:bg-indigo-700' : 'bg-gray-800'
          }`}
        >
          <Text className={`font-semibold text-base ${selectedRole ? 'text-white' : 'text-gray-600'}`}>
            Continue
          </Text>
        </Pressable>
        <Pressable onPress={skipOnboarding} className="py-2 items-center">
          <Text className="text-gray-500 text-sm">I'll set this up myself</Text>
        </Pressable>
      </View>
    </View>
  )

  // ── Step 1: Work preference ──────────────────────────────────────────────

  const renderRemotePicker = () => (
    <View className="flex-1">
      <Text className="text-white text-2xl font-bold mb-2">Where do you prefer to work?</Text>
      <Text className="text-gray-400 text-sm mb-6">This shapes how we filter and rank your results.</Text>
      <View className="gap-3 flex-1">
        {REMOTE_OPTIONS.map((opt) => {
          const selected = remotePref === opt.value
          return (
            <Pressable
              key={opt.value}
              onPress={() => setRemotePref(opt.value)}
              className={`flex-row items-center gap-4 px-4 py-4 rounded-xl border ${
                selected
                  ? 'bg-indigo-900/40 border-indigo-500'
                  : 'bg-gray-900 border-gray-800'
              }`}
            >
              <View className="flex-1">
                <Text className={`font-semibold text-sm ${selected ? 'text-indigo-300' : 'text-white'}`}>
                  {opt.label}
                </Text>
                <Text className="text-gray-500 text-xs mt-0.5">{opt.sub}</Text>
              </View>
              {selected && (
                <View className="w-5 h-5 rounded-full bg-indigo-500 items-center justify-center">
                  <Text className="text-white text-xs font-bold">✓</Text>
                </View>
              )}
            </Pressable>
          )
        })}
      </View>
      <View className="pt-6 gap-3">
        <Pressable
          onPress={() => setStep(2)}
          className="bg-indigo-600 active:bg-indigo-700 py-4 rounded-xl items-center"
        >
          <Text className="text-white font-semibold text-base">Continue</Text>
        </Pressable>
        <Pressable onPress={() => setStep(0)} className="py-2 items-center">
          <Text className="text-gray-500 text-sm">← Back</Text>
        </Pressable>
      </View>
    </View>
  )

  // ── Step 2: Location (optional) ──────────────────────────────────────────

  const renderLocationStep = () => (
    <View className="flex-1 justify-center">
      <Text className="text-white text-2xl font-bold mb-2">Add your location?</Text>
      <Text className="text-gray-400 text-sm mb-8">
        Atlas can surface local and hybrid jobs near you. You can set your location in Profile → Info after setup.
      </Text>
      <View className="gap-3">
        <Pressable
          onPress={() => { setStep(3); startCollection() }}
          className="bg-indigo-600 active:bg-indigo-700 py-4 rounded-xl items-center"
        >
          <Text className="text-white font-semibold text-base">Continue</Text>
        </Pressable>
        <Pressable onPress={() => setStep(1)} className="py-2 items-center">
          <Text className="text-gray-500 text-sm">← Back</Text>
        </Pressable>
      </View>
    </View>
  )

  // ── Step 3: Loading / collection ─────────────────────────────────────────

  const startCollection = useCallback(async () => {
    if (!selectedRole) return
    setLoading(true)

    try {
      setStatusText('Creating your profile…')
      const profile = await api.createProfileFromTemplate(selectedRole, remotePref)
      setActiveProfile(profile.id as any, profile.slug)

      setStatusText('Finding your jobs…')
      await api.findJobs()

      setStatusText('Building your feed…')
      setOnboardingDismissed(true)
      router.replace('/(tabs)')
    } catch (err: any) {
      setLoading(false)
      Alert.alert(
        'Setup failed',
        err?.message ?? 'Something went wrong. Please try again.',
        [{ text: 'Retry', onPress: () => startCollection() }, { text: 'Skip', onPress: skipOnboarding }]
      )
    }
  }, [selectedRole, remotePref, setActiveProfile, setOnboardingDismissed, router, skipOnboarding])

  const renderLoading = () => (
    <View className="flex-1 justify-center items-center gap-6">
      <ActivityIndicator size="large" color="#6366f1" />
      <View className="items-center gap-2">
        <Text className="text-white text-lg font-semibold">{statusText}</Text>
        <Text className="text-gray-500 text-sm text-center">
          This takes about 30 seconds on the first run.
        </Text>
      </View>
    </View>
  )

  // ── Layout ───────────────────────────────────────────────────────────────

  const TOTAL_STEPS = 3 // dots: role, remote, location (loading has no dot)

  return (
    <View className="flex-1 bg-gray-950">
      {/* Header */}
      <View className="px-6 pt-16 pb-4">
        <View className="flex-row items-center justify-between mb-6">
          <Text className="text-indigo-400 font-bold text-lg tracking-wide">Atlas</Text>
          {step < 3 && (
            <Pressable onPress={skipOnboarding}>
              <Text className="text-gray-500 text-sm">Skip</Text>
            </Pressable>
          )}
        </View>
        {step < 3 && <StepDots current={step} total={TOTAL_STEPS} />}
      </View>

      {/* Content */}
      <View className="flex-1 px-6 pb-8">
        {step === 0 && renderRolePicker()}
        {step === 1 && renderRemotePicker()}
        {step === 2 && renderLocationStep()}
        {step === 3 && renderLoading()}
      </View>
    </View>
  )
}
