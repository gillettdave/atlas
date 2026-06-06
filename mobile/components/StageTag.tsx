import { View, Text } from 'react-native'

interface StageStyle {
  bg: string
  text: string
  label: string
}

const STAGES: Record<string, StageStyle> = {
  new:          { bg: 'bg-blue-950',    text: 'text-blue-300',    label: 'New' },
  applied:      { bg: 'bg-indigo-950',  text: 'text-indigo-300',  label: 'Applied' },
  screening:    { bg: 'bg-purple-950',  text: 'text-purple-300',  label: 'Screening' },
  interviewing: { bg: 'bg-amber-950',   text: 'text-amber-300',   label: 'Interviewing' },
  offer:        { bg: 'bg-emerald-950', text: 'text-emerald-300', label: 'Offer' },
  rejected:     { bg: 'bg-red-950',     text: 'text-red-400',     label: 'Rejected' },
  archived:     { bg: 'bg-gray-800',    text: 'text-gray-500',    label: 'Archived' },
}

interface Props {
  stage: string
}

export function StageTag({ stage }: Props) {
  const s = STAGES[stage.toLowerCase()] ?? {
    bg: 'bg-gray-800',
    text: 'text-gray-400',
    label: stage,
  }

  return (
    <View className={`rounded px-2 py-0.5 ${s.bg}`}>
      <Text className={`text-xs font-medium ${s.text}`}>{s.label}</Text>
    </View>
  )
}
