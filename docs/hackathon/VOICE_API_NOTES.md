# Meta Voice Transcribe: API notes for the voice-query surface

Read 2026-10-27 from Meta's official developer docs. Everything in the
"Documented" table comes from the pages linked below. The section after it
lists what is **not** documented and how the client handles it.

## Sources

| Page | URL |
|---|---|
| Speech to text (guide: file endpoint, limits, pricing) | https://dev.meta.ai/docs/speech-to-text |
| API reference: transcribe a recording | https://dev.meta.ai/docs/api-reference/voice/transcribe |
| API reference: voice schemas | https://dev.meta.ai/docs/api-reference/voice/schemas |
| API reference: realtime (WebSocket, not used) | https://dev.meta.ai/docs/api-reference/voice/realtime |
| Error handling | https://dev.meta.ai/docs/error-handling |

Third-party corroboration of the model id and realtime URL (not authoritative):
LiveKit (https://docs.livekit.io/agents/models/stt/meta/), Pipecat
(https://docs.pipecat.ai/api-reference/server/services/stt/meta), LiteLLM
(https://docs.litellm.ai/docs/providers/meta.md). All three use
`muse-voice-transcribe-1.0` and `wss://api.meta.ai/v1/asr/realtime`.

## Documented

| Item | Value | Constant in `copilot/voice.py` |
|---|---|---|
| Endpoint | `POST https://api.meta.ai/v1/asr/transcribe` (optional `?sessionId=`) | `DEFAULT_BASE_URL` + `TRANSCRIBE_PATH` |
| Auth | `Authorization: Bearer <Meta Model API key>` (same key as chat) | header built in `transcribe_bytes` |
| Response format | `Accept: application/json` (also `text/event-stream`, `text/plain`; others → 406) | `Accept` header |
| Body | `multipart/form-data` with two parts | |
| Part `request` | JSON settings, `application/json` | `FIELD_REQUEST` |
| Part `audio` | the clip, `audio/wav` | `FIELD_AUDIO` |
| `request.model` | `muse-voice-transcribe-1.0` (required) | `DEFAULT_VOICE_MODEL` |
| `request.audioEncoding` | `WAV`, the only value (required) | `AUDIO_ENCODING` |
| `request.mode` | `PUSH_TO_TALK` (default), `ENDPOINTING`, `DIARIZATION` | `MODE` |
| `request.languageBias` | e.g. `["English"]`; omit to let the model detect | `DEFAULT_LANGUAGE_BIAS` |
| `request.keywords` | terms to bias recognition toward | `DEFAULT_KEYWORDS` |
| Audio format | RIFF/WAVE, mono, 16-bit PCM, 16 kHz or 24 kHz. Convert others: `ffmpeg -i in.m4a -ac 1 -ar 24000 -c:a pcm_s16le -map_metadata -1 out.wav` | `SUPPORTED_SAMPLE_RATES`, `validate_audio` |
| Size limit | request body ≤ 32 MB (413 above) | `MAX_BODY_BYTES` (decimal MB, the safer reading) |
| Duration limit | ≤ 10 minutes (400 above) | `MAX_AUDIO_SECONDS` |
| Response JSON | `sessionId` (str), `transcript` (str, whole clip), `audioDurationMs` (int), `turns` (list of `turnId`, `startMs`, `endMs`, `transcript`, `speaker`; empty in `PUSH_TO_TALK`) | `RESPONSE_*` |
| Errors | 400 bad WAV / >10 min / not multipart; 406; 413; 429 limits; 500 failure. Body: `{"error": {"message", "type", "param", "code"}}` | `_error_message` |
| Retry | 429, 500, 503 retryable with backoff; 400/401/402/403/404/413 are not | `RETRYABLE_STATUS` (exposed as `.retryable`, no automatic retry) |
| Pricing | **$0.18 per hour of audio**, billed in whole seconds rounded down; streaming and file are priced the same; failed requests and 429s are not billed | `VOICE_USD_PER_AUDIO_HOUR`, `estimate_cost_usd` |

The $0.18 per audio hour figure from earlier notes is **confirmed** on the
speech-to-text page. A 3-second question costs about $0.00015.

## Not documented, and how the client handles it

- **No detected-language field.** Neither the request nor the response has one,
  and word-level timestamps and confidence scores are documented as unavailable.
  `Transcript.language` is the single `languageBias` value we sent (`"English"`).
  If a future response has a `language` key, the client uses it. Read the
  dashboard's "English" as "biased to English", not as detection.
- **`zdrOverride`** (zero data retention) is listed by Pipecat but not on the
  schema page we read. We don't send it.
- **Error `code` values** are not enumerated. We show `type`, `message` and `code`
  verbatim.
- **What Streamlit records.** `st.audio_input(sample_rate=16000)` (Streamlit
  1.66.1 here) records WAV. We did not check in a browser that the file is mono
  16-bit. `validate_audio` rejects anything else with a clear message before
  upload, so a mismatch shows as an error, not a wasted call.

## Why the file endpoint and not the WebSocket

One question is a short clip, so a single request/response is simpler to test
(`httpx.MockTransport`), to record into a transcript, and to audit. The
realtime endpoint needs continuous PCM frames (silence included) and a 60-minute
session cap. That suits live captions, not push-to-talk Q&A.

## Why audio never goes to Muse Spark

Spark 1.3's audio input is degraded. The pipeline is: WAV → Voice Transcribe →
transcript text → `CopilotAgent.ask(text)` → the same claim-level gate. The
transcript is shown above the answer ("🎙 Heard: …") so the analyst can catch a
mis-hearing before trusting the answer. A clip with no speech raises
`VoiceTranscribeError` and the chat model is never called.

## Demo audio

The demo questions are two text-to-speech samples Charan made with
ElevenLabs (not a recording of a real practitioner, and the demo never says
otherwise): `demo/voice/question-a.wav` (14.2 s) and `demo/voice/question-b.wav`
(10.2 s), both converted to mono 16 kHz 16-bit with metadata stripped:

    ffmpeg -i sample.mp3 -ac 1 -ar 16000 -c:a pcm_s16le -map_metadata -1 demo/voice/question-a.wav

The earlier robotic `flite` placeholder (`question.wav`) was removed; Piper is
not used. The record workflow transcribes every `demo/voice/question*.wav` (`question.wav` is labelled `00-voice-main`)
and answers each, labelled `00-voice-a`, `00-voice-b`.

Record (needs the key; CI does this from the repository secret):

    python scripts/record_demo_transcripts.py --voice-file demo/voice/question-a.wav \
        --voice-label 00-voice-a
