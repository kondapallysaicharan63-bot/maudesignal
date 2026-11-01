// The one place the v2 chat screen gets its answer rendering from. The answer turn (model chip, Details, action bar,
// read-aloud, answer typography) is owned by components/LiveChat.tsx; the v2 shell only lays turns out in a column
// and always asks for the v2 answer turn.
import type { ComponentProps } from 'react'
import { TurnView } from '../components/LiveChat'

export function ChatTurn(props: Omit<ComponentProps<typeof TurnView>, 'v2'>) {
  return <TurnView {...props} v2 />
}
