import { Stack, useRouter, useSegments } from 'expo-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StatusBar } from 'expo-status-bar'
import { useEffect } from 'react'
import { useConfigStore } from '../stores/config'
import '../global.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 2,
      retry: 1,
    },
  },
})

/** Redirect to onboarding when no profile is set and onboarding hasn't been dismissed. */
function OnboardingGate() {
  const router = useRouter()
  const segments = useSegments()
  const { onboardingDismissed, activeProfileId } = useConfigStore()

  useEffect(() => {
    const timer = setTimeout(() => {
      const inOnboarding = (segments[0] as string) === 'onboarding'
      const needsOnboarding = !onboardingDismissed && !activeProfileId

      if (needsOnboarding && !inOnboarding) {
        router.replace('/onboarding' as any)
      } else if (!needsOnboarding && inOnboarding) {
        router.replace('/(tabs)')
      }
    }, 100)
    return () => clearTimeout(timer)
  }, [onboardingDismissed, activeProfileId, segments])

  return null
}

export default function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <StatusBar style="light" />
      <OnboardingGate />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: '#030712' },
        }}
      />
    </QueryClientProvider>
  )
}
