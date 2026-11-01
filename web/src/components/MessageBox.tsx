// The message box with one "+" menu (behind VITE_FEATURE_COMPOSER_MENU; ?composer=classic shows the earlier composer).
// The menu holds: Take photo · Upload photo · Try a sample label · Web research (only when the API offers it) · Ask by
// voice. A photo shows as a thumbnail above the box until it is sent or removed. Voice swaps the box for a recording bar;
// Stop turns the recording into words in the box, and nothing is sent until the person presses Send.
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { STREAMLIT_URL } from '../data'
import { Icon } from '../icons'
import { checkQuestion, MAX_SOURCE_BYTES, transcribeErrorText, type TranscribeResult } from '../live/api'
import { applyCodeSuggestion, heardCodeFor } from '../live/codeSuggest'
import type { ApiFeatures } from '../live/features'
import { fileToJpeg, PHOTO_ENCODE_FAILED_TEXT, PHOTO_TOO_BIG_TEXT, PhotoError } from '../live/photo'
import { useRecorder } from '../live/useRecorder'
import { closestThread } from '../match'
import { exactKnownCode, moveActive, suggest, type CodeInfo, type Suggestion } from '../typeahead'
import type { Thread } from '../types'
import { CameraSheet } from './CameraSheet'
import { DISCLAIMER, Marked, SUGGESTED } from './Composer'
import { PlusMenu, type MenuItem } from './PlusMenu'
import { VoiceBar } from './VoiceBar'

export interface MessageBoxLive {
  /** Sends a typed (or transcribed and edited) question; returns a message when it was refused before sending. */
  onAsk: (q: string, o: { research: boolean }) => string | null
  /**
   * Sends a label photo (one turn in the conversation). Words typed with it are asked after the reading returns, with
   * the top match's product code when it has one.
   */
  onPhoto: (jpeg: Blob, followUp: { question: string; research: boolean } | null) => void
  /** The words of a recording only; nothing is asked. Used only when GET /v1/health confirms voice_transcribe_only. */
  transcribe: (wav: Blob) => Promise<TranscribeResult>
  busy: boolean
  features: ApiFeatures
}

interface Props {
  threads: Thread[]
  onThread: (id: string) => void
  viewKey: string
  codes: CodeInfo[]
  onCode: (code: string) => void
  /** Without the live API: the label screen with its recorded runs. */
  onCamera: () => void
  /** Without the live API (or when the microphone cannot be used): the voice screen with its recorded runs. */
  onMic: () => void
  /** "Try a sample label": the stored sample label photos and their readings. */
  onSample: () => void
  live?: MessageBoxLive | null
  /** Test hook: true makes "Take photo" use the phone camera input instead of the live preview. */
  phone?: boolean
  /** Told when a recording starts and ends (v2 shows the audio note only while recording). */
  onRecording?: (on: boolean) => void
}

/** A phone or tablet: a touch screen as the main pointer, or a mobile browser. Its own camera app takes the photo. */
export function isPhoneLike(): boolean {
  if (typeof window === 'undefined') return false
  const coarse = !!window.matchMedia?.('(pointer: coarse)').matches
  const ua = typeof navigator === 'undefined' ? '' : navigator.userAgent
  return (coarse && !!window.matchMedia?.('(max-width: 1024px)').matches) || /Android|iPhone|iPad|iPod|Mobile/i.test(ua)
}

type Notice = ({ kind: 'match'; question: string } | { kind: 'live' }) & { forKey: string }
interface Photo {
  blob: Blob
  url: string
}

export function MessageBox({ threads, onThread, viewKey, codes, onCode, onCamera, onMic, onSample, live = null, phone, onRecording }: Props) {
  const [text, setText] = useState('')
  const [askError, setAskError] = useState<string | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const [saved, setNotice] = useState<Notice | null>(null)
  const notice = saved && saved.forKey === viewKey ? saved : null
  const [focus, setFocus] = useState(false)
  const [active, setActive] = useState(-1)
  const listId = useId()
  const wrapRef = useRef<HTMLDivElement>(null)
  const uploadRef = useRef<HTMLInputElement>(null)
  const phoneCamRef = useRef<HTMLInputElement>(null)

  const [photo, setPhoto] = useState<Photo | null>(null)
  const [photoNote, setPhotoNote] = useState<{ text: string; pick: boolean } | null>(null)
  const [camera, setCamera] = useState(false)
  const [research, setResearch] = useState(false)
  const [voiceNote, setVoiceNote] = useState<string | null>(null)
  const [transcribing, setTranscribing] = useState(false)
  const [didYouMean, setDidYouMean] = useState<string[]>([])
  const [voiceLeft, setVoiceLeft] = useState<number | null>(null)

  const researchOn = !!live?.features.research && research
  // Voice in the box needs transcribe-only, confirmed by the API. Until then the item opens the recorded voice run;
  // a recording is never sent as a question by itself.
  const voiceLive = !!live?.features.transcribeOnly
  const [showDetails, setShowDetails] = useState(false)
  // While the box is in use, the alert buddy's speech bubble (top bar) is hidden so nothing overlaps.
  const [inUse, setInUse] = useState(false)

  // Focus moved here by the page (after a transcript, a photo, Cancel) does not open the list of recorded questions;
  // only the person's own focus or typing does.
  const quiet = useRef(false)
  const focusBox = (toEnd = false) => {
    const el = inputRef.current
    if (!el) return
    if (document.activeElement !== el) quiet.current = true
    el.focus()
    if (toEnd) el.setSelectionRange(el.value.length, el.value.length)
  }

  // The recording: Stop -> WAV -> words in the box (or, on an older API, the one-call voice answer as before).
  const rec = useRecorder({
    pauseAtLimit: true,
    onResult: (r) => {
      if (!live || !live.features.transcribeOnly) return // never sent without the transcribe-only option
      setTranscribing(true)
      live
        .transcribe(r.wav)
        .then((res) => {
          setText((cur) => (cur.trim() ? `${cur.trimEnd()} ${res.heard}` : res.heard))
          setDidYouMean(res.did_you_mean.filter((c) => heardCodeFor(res.heard, c)))
          setVoiceLeft(res.limits ? res.limits.remaining_today : null)
          setVoiceNote(null)
          setFocus(false)
          // The words are in the box for editing; the cursor goes to their end.
          window.setTimeout(() => {
            const el = inputRef.current
            if (!el) return
            focusBox(true)
            el.style.height = 'auto'
            el.style.height = `${Math.min(el.scrollHeight, 112)}px`
          }, 0)
        })
        .catch((e: unknown) => {
          setVoiceNote(transcribeErrorText(e))
          window.setTimeout(() => focusBox(), 0)
        })
        .finally(() => setTranscribing(false))
    },
    onError: (message) => setVoiceNote(message),
  })
  const recording = rec.state !== 'idle' || transcribing
  const onRecordingRef = useRef(onRecording)
  onRecordingRef.current = onRecording
  useEffect(() => {
    onRecordingRef.current?.(recording)
  }, [recording])
  // On a page with the message box the alert buddy's first-visit bubble is not shown (it can cover the claims strip).
  useEffect(() => {
    document.body.dataset.composerMenu = 'true'
    return () => {
      delete document.body.dataset.composerMenu
    }
  }, [])
  useEffect(() => {
    const on = inUse || recording || camera
    if (on) document.body.dataset.composerActive = 'true'
    else delete document.body.dataset.composerActive
    return () => {
      delete document.body.dataset.composerActive
    }
  }, [inUse, recording, camera])
  // After Cancel the box comes back with focus in it.
  const wasRecording = useRef(false)
  useEffect(() => {
    if (wasRecording.current && !recording) focusBox(true)
    wasRecording.current = recording
  }, [recording])

  // The thumbnail's address is released when the photo is removed or sent.
  useEffect(() => () => {
    if (photo) URL.revokeObjectURL(photo.url)
  }, [photo])

  const starters = useMemo(
    () => SUGGESTED.map((id) => threads.find((t) => t.id === id)).filter((t): t is Thread => !!t),
    [threads],
  )
  const typed = text.trim().length > 0
  const options = useMemo<Suggestion[]>(
    () => (typed ? suggest(text, threads, codes) : starters.map((thread) => ({ kind: 'question' as const, thread }))),
    [typed, text, threads, codes, starters],
  )
  // The type-ahead of recorded questions; not while a photo waits (Send then sends the photo).
  const open = focus && options.length > 0 && !photo
  useEffect(() => {
    if (open && active >= 0) document.getElementById(`${listId}-${active}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [open, active, listId])

  const attach = async (f: File | Blob | undefined, fromFile: boolean) => {
    if (!f) return
    setPhotoNote(null)
    if (f.size === 0) return setPhotoNote({ text: 'That file is empty.', pick: false })
    if (f.size > MAX_SOURCE_BYTES) return setPhotoNote({ text: `That file is too large to read here. Choose a photo under ${MAX_SOURCE_BYTES / (1024 * 1024)} MB.`, pick: false })
    if (fromFile && f.type && !f.type.startsWith('image/')) return setPhotoNote({ text: 'That file is not an image. Choose a JPEG or PNG photo.', pick: false })
    let jpeg: Blob
    try {
      // The original file is never sent: it is drawn again as a fresh JPEG without metadata.
      jpeg = fromFile ? await fileToJpeg(f as File) : f
    } catch (e) {
      if (e instanceof PhotoError && e.kind === 'too_big') return setPhotoNote({ text: PHOTO_TOO_BIG_TEXT, pick: false })
      if (e instanceof PhotoError && e.kind === 'encode_failed') return setPhotoNote({ text: PHOTO_ENCODE_FAILED_TEXT, pick: false })
      return setPhotoNote({ text: 'That image could not be read in this browser. Choose a JPEG or PNG photo.', pick: false })
    }
    setPhoto({ blob: jpeg, url: URL.createObjectURL(jpeg) })
    window.setTimeout(() => focusBox(), 0)
  }

  const removePhoto = () => {
    setPhoto(null)
    focusBox()
  }

  const takePhoto = () => {
    if (!live) return onCamera()
    setPhotoNote(null)
    if (phone ?? isPhoneLike()) phoneCamRef.current?.click()
    else setCamera(true)
  }

  const startVoice = () => {
    if (!live || !voiceLive) return onMic()
    setVoiceNote(null)
    setDidYouMean([])
    void rec.start()
  }

  const items: MenuItem[] = [
    { id: 'take-photo', label: 'Take photo', icon: 'camera', hint: 'Photograph a device label', onSelect: takePhoto },
    { id: 'upload-photo', label: 'Upload photo', icon: 'upload', hint: 'Choose a label photo', onSelect: () => (live ? uploadRef.current?.click() : onCamera()) },
    { id: 'sample-label', label: 'Try a sample label', icon: 'image', hint: 'Recorded example photos', onSelect: onSample },
    ...(live?.features.research
      ? [{ id: 'research', label: 'Web research', icon: 'globe' as const, hint: 'Not FDA records', checked: research, onSelect: () => setResearch((r) => !r) }]
      : []),
    {
      id: 'voice',
      label: 'Ask by voice',
      icon: 'mic',
      hint: !live
        ? 'Opens the recorded voice run'
        : !voiceLive
          ? 'Voice needs the live service — opens the recorded voice run'
          : voiceLeft !== null
            ? `${voiceLeft} voice ${voiceLeft === 1 ? 'question' : 'questions'} left today · you edit the words before sending`
            : 'You edit the words before sending',
      onSelect: startVoice,
    },
  ]

  const pick = (sg: Suggestion) => {
    setNotice(null)
    setText('')
    setFocus(false)
    setActive(-1)
    if (sg.kind === 'code') onCode(sg.code)
    else onThread(sg.thread.id)
  }

  const submit = () => {
    if (open && active >= 0 && options[active]) return pick(options[active])
    if (photo && live) {
      if (live.busy) return setAskError('Wait for the current answer to finish, then send the next one.')
      const q = text.trim()
      if (q) {
        try {
          checkQuestion(q)
        } catch (e) {
          return setAskError((e as Error).message)
        }
      }
      // Any words typed with the photo are asked after the label reading (two steps; the turn says so).
      live.onPhoto(photo.blob, q ? { question: q, research: researchOn } : null)
      setPhoto(null)
      setText('')
      setAskError(null)
      setDidYouMean([])
      inputRef.current?.focus()
      return
    }
    if (!typed) return
    const known = exactKnownCode(text, codes)
    if (known) {
      setText('')
      setFocus(false)
      return onCode(known)
    }
    if (live) {
      if (live.busy) {
        setAskError('Wait for the current answer to finish, then send the next question.')
        return
      }
      const refused = live.onAsk(text, { research: researchOn })
      setAskError(refused)
      setFocus(false)
      if (!refused) {
        setText('')
        setDidYouMean([])
      }
      inputRef.current?.focus()
      return
    }
    const m = closestThread(text, threads)
    if (/^[A-Za-z]{3}$/.test(text.trim()) && !m) {
      const c = text.trim().toUpperCase()
      setText('')
      setFocus(false)
      return onCode(c)
    }
    if (m) {
      setNotice({ kind: 'match', question: m.thread.question, forKey: `thread:${m.thread.id}` })
      setText('')
      setFocus(false)
      onThread(m.thread.id)
    } else setNotice({ kind: 'live', forKey: viewKey })
  }

  return (
    <div
      ref={wrapRef}
      className={['relative shrink-0 border-t border-rule bg-paper px-3 pb-[calc(0.5rem+env(safe-area-inset-bottom))] pt-2 md:px-6', open ? 'z-40' : 'z-20'].join(' ')}
      data-testid="composer"
      data-composer="menu"
      onFocusCapture={() => setInUse(true)}
      onBlurCapture={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setInUse(false)
      }}
    >
      {open && (
        <div
          className="ws-scrim pointer-events-none !bottom-auto"
          style={{ height: `calc(100% - ${wrapRef.current?.offsetHeight ?? 0}px)` }}
          aria-hidden="true"
          data-testid="typeahead-scrim"
        />
      )}
      {/* The hidden pickers: a phone's own camera, and a photo file. */}
      <input
        ref={phoneCamRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="phone-camera-input"
        onChange={(e) => {
          void attach(e.target.files?.[0], true)
          e.target.value = ''
        }}
      />
      <input
        ref={uploadRef}
        type="file"
        accept="image/jpeg,image/png,image/*"
        className="sr-only"
        tabIndex={-1}
        aria-label="Upload photo of a device label"
        data-testid="photo-input"
        onChange={(e) => {
          void attach(e.target.files?.[0], true)
          e.target.value = ''
        }}
      />
      {camera && (
        <CameraSheet
          onUse={(jpeg) => {
            setCamera(false)
            void attach(jpeg, false)
          }}
          onClose={() => {
            setCamera(false)
            focusBox()
          }}
          onPickFile={() => {
            setCamera(false)
            setPhotoNote(null)
            uploadRef.current?.click()
          }}
          onFail={(reason) => {
            setCamera(false)
            setPhotoNote({ text: reason, pick: true })
            // Straight to the file picker (the button in the note does the same if the browser blocks this).
            uploadRef.current?.click()
          }}
        />
      )}
      <div className="relative mx-auto max-w-3xl">
        {notice && (
          <div role="status" className="ms-banner ms-banner--info mb-2 text-[16px]">
            {notice.kind === 'match' ? (
              <p className="ws-wrap m-0">
                <strong>Closest recorded answer:</strong> {notice.question}
              </p>
            ) : (
              <p className="ws-wrap m-0">
                <strong>No recorded question is close to that.</strong> Live questions run in the Streamlit app, where the copilot asks the model
                in real time.{' '}
                <a href={STREAMLIT_URL} target="_blank" rel="noreferrer" className="font-semibold underline">
                  Ask live
                </a>
              </p>
            )}
          </div>
        )}
        {askError && (
          <p role="alert" className="ms-banner ms-banner--warn relative z-10 mb-2 text-[16px]" data-testid="ask-error">
            <span className="ws-wrap">{askError}</span>
          </p>
        )}
        {photoNote && (
          <div role="alert" className="ms-banner ms-banner--warn relative z-10 mb-2 flex flex-wrap items-center gap-2 text-[16px]" data-testid="photo-note">
            <span className="ws-wrap min-w-0 flex-1">{photoNote.text}</span>
            {photoNote.pick && (
              <button type="button" className="ms-btn ms-btn--secondary !min-h-11" onClick={() => uploadRef.current?.click()} data-testid="photo-note-pick">
                <Icon name="upload" size={18} /> Choose a photo
              </button>
            )}
          </div>
        )}
        {voiceNote && (
          <div role="alert" className="ms-banner ms-banner--warn relative z-10 mb-2 flex flex-wrap items-center gap-2 text-[16px]" data-testid="voice-problem">
            <span className="ws-wrap min-w-0 flex-1">{voiceNote}</span>
            <button type="button" className="ms-btn ms-btn--secondary !min-h-11" onClick={onMic}>
              Open the recorded voice run
            </button>
          </div>
        )}
        {recording ? (
          <VoiceBar
            rec={rec}
            transcribing={transcribing}
            title={voiceLeft !== null ? `${voiceLeft} voice ${voiceLeft === 1 ? 'question' : 'questions'} left today` : undefined}
          />
        ) : (
          <form
            className="relative z-10 rounded-lg border border-rule bg-surface p-2 shadow-[var(--shadow-pop)]"
            onSubmit={(e) => {
              e.preventDefault()
              submit()
            }}
            data-testid="message-box"
          >
            {open && (
              <div
                data-popover-open
                className="absolute inset-x-0 bottom-full z-40 mb-1 flex flex-col overflow-hidden rounded-md border-2 border-rule-strong bg-surface shadow-[var(--shadow-pop)]"
              >
                <p className="m-0 border-b border-rule px-3 py-1.5 text-[15px] font-semibold text-ink-2" id={`${listId}-h`}>
                  {typed ? 'Recorded questions and device codes' : 'Recorded questions you can open'} · <span className="ms-num">{options.length}</span>
                </p>
                <ul
                  id={listId}
                  role="listbox"
                  aria-labelledby={`${listId}-h`}
                  className="ws-fade-bottom m-0 max-h-[min(19rem,40dvh)] list-none overflow-y-auto overscroll-contain p-1 pb-5"
                >
                  {options.map((sg, i) => (
                    <li
                      key={sg.kind === 'code' ? `code-${sg.code}` : sg.thread.id}
                      id={`${listId}-${i}`}
                      role="option"
                      aria-selected={i === active}
                      onMouseDown={(e) => {
                        e.preventDefault()
                        pick(sg)
                      }}
                      onMouseMove={() => i !== active && setActive(i)}
                      className={[
                        'flex min-h-11 cursor-pointer items-start gap-2 rounded-xs px-3 py-2 text-[17px] leading-snug text-ink',
                        i === active ? 'bg-accent-soft shadow-[inset_4px_0_0_var(--accent)]' : 'hover:bg-sunk',
                      ].join(' ')}
                    >
                      {sg.kind === 'code' ? (
                        <span className="ws-wrap min-w-0 flex-1">
                          <span className="ms-code mr-2 !text-[17px] !text-ink">
                            <Marked text={sg.code} query={text} />
                          </span>
                          Check any device type
                          {sg.name ? (
                            <span className="text-ink-2">
                              {' '}
                              · <Marked text={sg.name} query={text} />
                            </span>
                          ) : null}
                        </span>
                      ) : (
                        <span className="ws-wrap min-w-0 flex-1">
                          <Marked text={sg.thread.question} query={text} />
                        </span>
                      )}
                      <span className={['mt-0.5 shrink-0', i === active ? 'text-accent' : 'text-ink-2'].join(' ')}>
                        <Icon name="chevron" size={18} />
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="m-0 border-t border-rule px-3 py-1.5 text-[15px] text-ink-2" data-testid="typeahead-hint">
                  <span className="sm:hidden">Tap a row to open it.</span>
                  <span className="max-sm:hidden">
                    <kbd className="ms-code !text-[15px] !text-ink">↑ ↓</kbd> move · <kbd className="ms-code !text-[15px] !text-ink">Enter</kbd> to open ·{' '}
                    <kbd className="ms-code !text-[15px] !text-ink">Esc</kbd> close
                  </span>
                </p>
              </div>
            )}
            {didYouMean.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 px-2 pb-1 pt-0.5 text-[16px] text-ink" data-testid="did-you-mean">
                <span className="inline-flex flex-wrap items-center gap-1 rounded-full border-0 bg-accent-soft px-3 py-1 text-[16px] font-semibold text-ink">
                  <span>
                    Did you mean <span className="ms-code !text-ink">{didYouMean.join(' or ')}</span>?
                  </span>
                  <span className="sr-only">Heard {heardCodeFor(text, didYouMean[0]) ?? 'a code'}, which is not a product code on file.</span>
                  {didYouMean.map((c) => (
                    <button
                      key={c}
                      type="button"
                      className="ml-1 inline-flex min-h-11 items-center rounded-full px-3 font-semibold text-accent underline hover:bg-sunk"
                      onClick={() => {
                        setText((t) => applyCodeSuggestion(t, c))
                        setDidYouMean([])
                        focusBox(true)
                      }}
                      aria-label={`Use ${c} instead of the heard code`}
                      data-testid="did-you-mean-code"
                    >
                      Use {c}
                    </button>
                  ))}
                  <button
                    type="button"
                    className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-full text-ink-2 hover:bg-sunk"
                    onClick={() => {
                      setDidYouMean([])
                      focusBox(true)
                    }}
                    aria-label="Keep the words as heard"
                  >
                    <Icon name="close" size={16} />
                  </button>
                </span>
              </div>
            )}
            {(photo || researchOn) && (
              <div className="flex flex-wrap items-center gap-2 px-1.5 pb-1.5 pt-0.5" data-testid="attachments">
                {photo && (
                  <span className="relative inline-block h-[72px] w-[72px]" data-testid="photo-thumb">
                    <img src={photo.url} alt="Attached label photo" className="block h-full w-full rounded-md border border-rule object-cover" />
                    {/* 44 x 44 hit area; the visible 24px circle sits 6px inside the thumbnail's corner. */}
                    <button
                      type="button"
                      onClick={removePhoto}
                      aria-label="Remove the attached photo"
                      className="group absolute right-0 top-0 flex h-11 w-11 items-start justify-end p-[6px]"
                      data-testid="photo-remove"
                    >
                      <span className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-rule-strong bg-surface text-ink group-hover:bg-sunk">
                        <Icon name="close" size={14} />
                      </span>
                    </button>
                  </span>
                )}
                {researchOn && (
                  <span className="ws-pill ws-pill--ring bg-accent-soft text-accent" data-testid="research-pill">
                    <Icon name="globe" size={16} /> Web research on
                    <button
                      type="button"
                      className="-my-1 ml-1 inline-flex min-h-8 min-w-8 items-center justify-center rounded-xs hover:bg-sunk"
                      onClick={() => setResearch(false)}
                      aria-label="Turn off web research"
                    >
                      <Icon name="close" size={14} />
                    </button>
                  </span>
                )}
              </div>
            )}
            <textarea
              ref={inputRef}
              rows={1}
              value={text}
              onChange={(e) => {
                setText(e.target.value)
                setNotice(null)
                setAskError(null)
                setActive(-1)
                setFocus(true)
                e.target.style.height = 'auto'
                e.target.style.height = `${Math.min(e.target.scrollHeight, 112)}px`
              }}
              onFocus={() => {
                if (quiet.current) quiet.current = false
                else setFocus(true)
              }}
              onBlur={() => setFocus(false)}
              onKeyDown={(e) => {
                if (e.key === 'ArrowDown' && open) {
                  e.preventDefault()
                  setActive((i) => moveActive(i, 'ArrowDown', options.length))
                } else if (e.key === 'ArrowDown' && options.length && !photo) {
                  e.preventDefault()
                  setFocus(true)
                  setActive((i) => moveActive(i, 'ArrowDown', options.length))
                } else if (e.key === 'ArrowUp' && open) {
                  e.preventDefault()
                  setActive((i) => moveActive(i, 'ArrowUp', options.length))
                } else if (e.key === 'Escape' && open) {
                  e.stopPropagation()
                  setFocus(false)
                } else if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  submit()
                }
              }}
              role="combobox"
              aria-expanded={open}
              aria-controls={open ? listId : undefined}
              aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
              aria-autocomplete="list"
              aria-label="Ask a question"
              placeholder={photo ? 'Add a note or question (optional)' : 'Ask a question'}
              autoComplete="off"
              className="block max-h-28 min-h-11 w-full resize-none bg-transparent px-2 py-[10px] text-[17px] leading-6 text-ink placeholder:text-ink-2 focus:outline-none"
            />
            <div className="flex items-center gap-2">
              <PlusMenu items={items} />
              <span className="min-w-0 flex-1" />
              <button
                type="submit"
                className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent text-[var(--on-accent)] hover:opacity-90 disabled:bg-sunk disabled:text-ink-3 disabled:hover:opacity-100"
                disabled={live?.busy || (!typed && !photo)}
                aria-label={live ? (photo ? 'Send photo' : 'Send') : 'Open the closest recorded answer'}
                title={live ? (photo ? 'Send photo' : 'Send') : 'Open the closest recorded answer'}
                data-testid="composer-send"
              >
                <Icon name="send" size={22} />
              </button>
            </div>
          </form>
        )}
        <div className="relative z-10 m-0 mt-1.5 text-center text-[15px] leading-snug text-ink-2" data-testid="disclaimer">
          <p className="m-0">
            Signals for review. Not medical advice.{' '}
            <button
              type="button"
              className="inline-flex min-h-8 items-center px-1 font-semibold text-ink-2 underline hover:text-ink"
              aria-expanded={showDetails}
              aria-controls="composer-details"
              onClick={() => setShowDetails((v) => !v)}
              data-testid="disclaimer-details"
            >
              Details
            </button>
          </p>
          {showDetails && (
            <p id="composer-details" className="ws-wrap m-0 mx-auto mt-1 max-w-2xl text-[15px]">
              {DISCLAIMER}{' '}
              {live
                ? 'Enter sends, Shift+Enter adds a line. If the live service is unavailable, recorded runs are shown and labelled.'
                : 'Photo and voice show a recorded run until the live API answers.'}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
