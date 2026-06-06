import { View, Text } from 'react-native'

interface Props {
  score: number | null
  label?: string
  size?: 'sm' | 'md'
}

function bgColor(score: number | null): string {
  if (score == null) return 'bg-gray-800'
  if (score >= 75) return 'bg-emerald-950'
  if (score >= 50) return 'bg-yellow-950'
  return 'bg-red-950'
}

function textColor(score: number | null): string {
  if (score == null) return 'text-gray-500'
  if (score >= 75) return 'text-emerald-400'
  if (score >= 50) return 'text-yellow-400'
  return 'text-red-400'
}

export function ScoreBadge({ score, label, size = 'md' }: Props) {
  const padding = size === 'sm' ? 'px-2 py-0.5' : 'px-3 py-1'
  const fontSize = size === 'sm' ? 'text-xs' : 'text-sm'

  return (
    <View className={`rounded-full ${bgColor(score)} ${padding}`}>
      <Text className={`font-semibold ${textColor(score)} ${fontSize}`}>
        {label ? `${label} ` : ''}
        {score != null ? Math.round(score) : '—'}
      </Text>
    </View>
  )
}
