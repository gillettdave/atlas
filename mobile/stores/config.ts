import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import AsyncStorage from '@react-native-async-storage/async-storage'

interface ConfigState {
  apiBase: string
  adminToken: string
  activeProfileId: number | null
  activeProfileSlug: string | null
  onboardingDismissed: boolean
  setApiBase: (url: string) => void
  setAdminToken: (token: string) => void
  setActiveProfileId: (id: number | null) => void
  setActiveProfileSlug: (slug: string | null) => void
  setActiveProfile: (id: number | null, slug: string | null) => void
  setOnboardingDismissed: (dismissed: boolean) => void
}

export const useConfigStore = create<ConfigState>()(
  persist(
    (set) => ({
      apiBase: process.env.EXPO_PUBLIC_API_BASE ?? 'http://localhost:8000',
      adminToken: process.env.EXPO_PUBLIC_ADMIN_TOKEN ?? '',
      activeProfileId: null,
      activeProfileSlug: null,
      onboardingDismissed: false,
      setApiBase: (url) => set({ apiBase: url }),
      setAdminToken: (token) => set({ adminToken: token }),
      setActiveProfileId: (id) => set({ activeProfileId: id }),
      setActiveProfileSlug: (slug) => set({ activeProfileSlug: slug }),
      setActiveProfile: (id, slug) => set({ activeProfileId: id, activeProfileSlug: slug }),
      setOnboardingDismissed: (dismissed) => set({ onboardingDismissed: dismissed }),
    }),
    {
      name: 'atlas-config',
      storage: createJSONStorage(() => AsyncStorage),
    }
  )
)
