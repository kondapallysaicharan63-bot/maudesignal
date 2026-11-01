// The one place the v2 chat screen gets its answer rendering from. The answer turn (model chip, Details, action bar,
// read-aloud, answer typography) is owned by components/LiveChat.tsx; the v2 shell only lays turns out in a column.
// To swap in a new answer component, change this re-export; the props are (turn, chat, onRecordedVoice,
// onRecordedLabel, onAsk, onOpen).
export { TurnView as ChatTurn } from '../components/LiveChat'
