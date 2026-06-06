import { View, Text } from 'react-native'

interface Props {
  icon?: string
  title: string
  subtitle?: string
}

export function EmptyState({ icon = '📭', title, subtitle }: Props) {
  return (
    <View className="flex-1 items-center justify-center py-20 px-8">
      <Text className="text-4xl mb-4">{icon}</Text>
      <Text className="text-gray-200 text-lg font-semibold text-center mb-2">{title}</Text>
      {subtitle && (
        <Text className="text-gray-500 text-sm text-center leading-relaxed">{subtitle}</Text>
      )}
    </View>
  )
}
