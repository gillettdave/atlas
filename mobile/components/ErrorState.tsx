import { View, Text, Pressable } from 'react-native'

interface Props {
  title?: string
  /** Raw error message — useful during alpha testing. */
  message?: string
  onRetry?: () => void
}

/**
 * Full-screen error state shown when an API query fails.
 * Mirrors EmptyState's layout but adds a Retry button.
 */
export function ErrorState({
  title = 'Connection problem',
  message,
  onRetry,
}: Props) {
  return (
    <View className="flex-1 items-center justify-center py-20 px-8">
      <Text className="text-4xl mb-4">⚠️</Text>
      <Text className="text-gray-200 text-lg font-semibold text-center mb-2">
        {title}
      </Text>
      <Text className="text-gray-500 text-sm text-center leading-relaxed mb-6">
        {message
          ? message
          : "Couldn't reach the API. Check your connection or go to Settings → Test."}
      </Text>
      {onRetry && (
        <Pressable
          className="bg-indigo-600 rounded-xl px-8 py-3 active:opacity-75"
          onPress={onRetry}
        >
          <Text className="text-white font-semibold">Retry</Text>
        </Pressable>
      )}
    </View>
  )
}
