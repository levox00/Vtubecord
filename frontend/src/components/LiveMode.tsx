import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAppStore } from "../stores/appStore";
import {
  closeVoiceBrainSession,
  fetchSTT,
  fetchTTS,
  fetchSettings,
  heartbeatVoiceBrainSession,
  openVoiceBrainSession,
  sendChat,
} from "../lib/api";
import type { ChatResponse, VoiceBrainDecision, VoiceBrainSessionStatus } from "../types";
import { resolveChannelMasterPreset } from "../lib/channelRuntime";
import { Live2DCanvas } from "./Live2DCanvas";
import { OrbAnimation } from "./OrbAnimation";
import { ToolCallIndicators } from "./ToolCallIndicators";
import {
  Mic,
  MicOff,
  Headphones,
  HeadphoneOff,
  PhoneOff,
  X,
  MessageSquare,
  Send,
  ScreenShare,
  Brain,
} from "lucide-react";
import { sfxConnect, sfxDisconnect, sfxClick } from "../lib/sounds";

// --- VAD constants ---
const VAD_POLL_MS = 50;            // how often to check audio level
const SILENCE_THRESHOLD = 3;       // time-domain RMS deviation from 128 (0-128 scale)
const SPEECH_THRESHOLD = 8;        // above this = user is talking
const SILENCE_TIMEOUT_MS = 1500;   // how long silence before we send to STT
const MIN_SPEECH_MS = 400;         // minimum speech duration to bother processing
const BARGE_IN_THRESHOLD = 12;     // volume to trigger barge-in while AI speaking

type VoiceState = "idle" | "listening" | "user_speaking" | "processing" | "thinking" | "speaking";

const LIVE_CHANNEL = "live";

export function LiveMode() {
  const isThinking = useAppStore((s) => s.isThinking);
  const addMessage = useAppStore((s) => s.addMessage);
  const setConversationId = useAppStore((s) => s.setConversationId);
  const setThinking = useAppStore((s) => s.setThinking);
  const setError = useAppStore((s) => s.setError);
  const setLiveMode = useAppStore((s) => s.setLiveMode);
  const activeChannel = useAppStore((s) => s.activeChannel);
  const channels = useAppStore((s) => s.channels);
  const setActiveChannel = useAppStore((s) => s.setActiveChannel);
  const character = useAppStore((s) => s.character);
  const setChatEmotion = useAppStore((s) => s.setChatEmotion);
  const setExpressiveLabel = useAppStore((s) => s.setExpressiveLabel);
  const setAvatarAction = useAppStore((s) => s.setAvatarAction);
  const avatarMode = useAppStore((s) => s.avatarMode);
  const avatarModelPath = useAppStore((s) => s.avatarModelPath);
  const live2dIdlePreset = useAppStore((s) => s.live2dIdlePreset);
  const live2dIdleIntensity = useAppStore((s) => s.live2dIdleIntensity);
  const setAvatarMode = useAppStore((s) => s.setAvatarMode);
  const currentChannel = channels.find((channel) => channel.id === activeChannel);
  const channelId = currentChannel?.kind === "voice" ? activeChannel : LIVE_CHANNEL;
  const conversationId = useAppStore((s) => s.channelConversations[channelId]);
  const channelForRuntime = channels.find((channel) => channel.id === channelId);
  const channelRuntimeSettings = useAppStore((s) => s.channelRuntimeSettings[channelId]);
  const settingsPersisted = useAppStore((s) => s.settingsPersisted);
  const msgs = useAppStore((s) => s.channelMessages[channelId]) ?? [];
  const voiceBrainSessionId = useMemo(
    () => `web_voice:${channelId}:${crypto.randomUUID()}`,
    [channelId],
  );

  const displayedSettings = channelRuntimeSettings;
  const displayedAvatarModel = displayedSettings?.avatar_model || avatarModelPath;
  const displayedIdlePreset = displayedSettings?.avatar_idle_preset || live2dIdlePreset;
  const displayedIdleIntensity = displayedSettings?.avatar_idle_intensity ?? live2dIdleIntensity;
  const displayedAvatarMode = channelRuntimeSettings
    ? (displayedSettings?.avatar_model ? "model" : "orb")
    : avatarMode;

  useEffect(() => {
    void resolveChannelMasterPreset(channelForRuntime).catch((err) => {
      setError(err instanceof Error ? err.message : "Channel preset failed");
    });
  }, [channelForRuntime, setError]);

  const currentProfileId = settingsPersisted?.character_profile_id || character?.profile_id;
  const currentProfileName = settingsPersisted?.character_name || character?.name;
  const displayCharacterName = (message?: { character_profile_id?: string | null; character_name?: string | null }) => {
    if (message?.character_profile_id && currentProfileId && message.character_profile_id === currentProfileId && currentProfileName) {
      return currentProfileName;
    }
    return message?.character_name || displayedSettings?.character_name || currentProfileName || "AI";
  };
  const displayCharacterPicture = (message?: { character_profile_picture?: string | null }) => message?.character_profile_picture || displayedSettings?.character_profile_picture || character?.profile_picture || "";
  const displayCharacterKey = (message?: { character_profile_id?: string | null; character_name?: string | null; character_profile_picture?: string | null }) =>
    message?.character_profile_id || message?.character_name || message?.character_profile_picture || displayedSettings?.character_profile_id || character?.profile_id || character?.name || "AI";

  // --- Voice state ---
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [isMuted, setIsMuted] = useState(false);
  const [isDeafened, setIsDeafened] = useState(false);
  const [showChat, setShowChat] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [volumeLevel, setVolumeLevel] = useState(0);
  const [ttsAudio, setTtsAudio] = useState<HTMLAudioElement | null>(null);
  const [spokenText, setSpokenText] = useState("");
  const [partialTranscript, setPartialTranscript] = useState("");
  const [sttConfig, setSttConfig] = useState<{ provider?: string; model?: string; stream_chunk_ms?: number; stream_language?: string; streaming_enabled?: boolean } | null>(null);
  const [brainEnabled, setBrainEnabled] = useState(true);
  const [brainStatus, setBrainStatus] = useState<VoiceBrainSessionStatus | null>(null);
  const [brainDecision, setBrainDecision] = useState<VoiceBrainDecision | null>(null);

  // --- Refs ---
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Stale-closure prevention: VAD interval calls these refs, not the function directly
  const handleSendRef = useRef<(text?: string) => void>(() => {});
  const processRecordedAudioRef = useRef<() => void>(() => {});
  const speakTextRef = useRef<(text: string) => Promise<void>>(async () => undefined);

  // VAD refs
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const vadIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const sttSocketRef = useRef<WebSocket | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const streamingReadyRef = useRef(false);
  const pcmBufferRef = useRef<Float32Array>(new Float32Array(0));
  const flushStreamingRef = useRef<() => void>(() => {});

  // Timing refs
  const speechStartRef = useRef<number>(0);
  const silenceStartRef = useRef<number>(0);
  const isUserSpeakingRef = useRef(false);
  const brainSocketRef = useRef<WebSocket | null>(null);
  const brainHeartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const voiceStateRef = useRef<VoiceState>("idle");
  const isMutedRef = useRef(false);
  const conversationIdRef = useRef<string | null>(null);
  const destroyedRef = useRef(false);

  // Keep refs in sync
  useEffect(() => { voiceStateRef.current = voiceState; }, [voiceState]);
  useEffect(() => { isMutedRef.current = isMuted; }, [isMuted]);
  useEffect(() => { conversationIdRef.current = conversationId; }, [conversationId]);

  useEffect(() => {
    fetchSettings().then((value) => {
      const source = useAppStore.getState().channelRuntimeSettings[channelId] ?? value;
      setSttConfig({
        provider: source.stt_provider,
        model: source.stt_model,
        stream_chunk_ms: source.stt_stream_chunk_ms,
        stream_language: source.stt_stream_language,
        streaming_enabled: source.stt_streaming_enabled,
      });
    }).catch(() => setSttConfig(null));
  }, [channelId, channelRuntimeSettings]);

  // --- Escape to exit ---
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") exitLiveMode();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [activeChannel, setActiveChannel, setLiveMode]);

  // --- Stop TTS when new user message arrives ---
  useEffect(() => {
    const last = msgs[msgs.length - 1];
    if (last?.role === "user") stopSpeaking();
  }, [msgs]);

  // --- Scroll chat ---
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);

  // --- Cleanup on unmount ---
  useEffect(() => {
    destroyedRef.current = false;
    return () => {
      destroyedRef.current = true;
      sfxDisconnect();
      try { stopListening(); } catch { /* ignore cleanup errors */ }
      try { stopSpeaking(); } catch { /* ignore cleanup errors */ }
      if (brainHeartbeatRef.current) clearInterval(brainHeartbeatRef.current);
    };
  }, []);

  // =========================================================================
  // TTS — speak text aloud
  // =========================================================================
  function stopSpeaking() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    setTtsAudio(null);
    setSpokenText("");
    if (voiceStateRef.current === "speaking" && !isMutedRef.current) {
      setVoiceState("listening");
    }
  }

  async function speakText(text: string) {
    if (isDeafened || destroyedRef.current) return;
    try {
      // TTS synthesis is a processing state. Do not advertise speech—or move
      // the Live2D mouth—until a real audio element is ready to play.
      setVoiceState("processing");
      setSpokenText("");
      const blob = await fetchTTS(text, undefined, undefined, undefined, channelForRuntime?.masterPresetId);
      if (destroyedRef.current) return;
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      setTtsAudio(audio);

      audio.onended = () => {
        URL.revokeObjectURL(url);
        if (destroyedRef.current) return;
        setTtsAudio(null);
        setSpokenText("");
        if (voiceStateRef.current === "speaking" && !isMutedRef.current) {
          setVoiceState("listening");
        }
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        if (destroyedRef.current) return;
        setTtsAudio(null);
        setSpokenText("");
        if (voiceStateRef.current === "speaking" && !isMutedRef.current) {
          setVoiceState("listening");
        }
      };
      // Give React and Live2D time to attach the production audio analyser.
      // The renderer still keeps the mouth closed while the element is paused.
      await new Promise<void>((resolve) => {
        window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve()));
      });
      if (destroyedRef.current || audioRef.current !== audio) {
        audio.pause();
        URL.revokeObjectURL(url);
        return;
      }
      setSpokenText(text);
      setVoiceState("speaking");
      await audio.play();
    } catch {
      setTtsAudio(null);
      setSpokenText("");
      if (
        (voiceStateRef.current === "speaking" || voiceStateRef.current === "processing")
        && !isMutedRef.current
      ) {
        setVoiceState("listening");
      }
    }
  }
  speakTextRef.current = speakText;

  // =========================================================================
  // Chat — send message and get response
  // =========================================================================
  const handleSend = useCallback(
    async (text?: string) => {
      const msg = text?.trim();
      if (!msg || isThinking || destroyedRef.current) return;

      stopSpeaking();
      setAvatarAction({ emotion: "curiosity", gesture: "lean_in", intensity: 0.46, hold_ms: 900 });

      await resolveChannelMasterPreset(channelForRuntime);
      addMessage(channelId, {
        id: crypto.randomUUID(),
        role: "user",
        content: msg,
      });
      setVoiceState("thinking");
      setThinking(true);
      setError(null);

      try {
        const res = await sendChat(
          msg,
          conversationId,
          channelForRuntime?.masterPresetId,
          {
            source: "web_voice",
            sessionId: voiceBrainSessionId,
            situationalContext: "The user is present in the web live voice room and just spoke through the microphone or live chat sidebar.",
          },
        );
        setConversationId(channelId, res.conversation_id);
        // Set real-time emotion for Live2D
        if (res.emotion) setChatEmotion(res.emotion);
        setExpressiveLabel(res.expressive_label ?? null);
        setAvatarAction(res.avatar_action ?? null);
        addMessage(channelId, {
          id: res.message_id,
          role: "assistant",
          content: res.content,
          emotion: res.emotion,
          character_profile_id: res.character_profile_id,
          character_name: res.character_name,
          character_profile_picture: res.character_profile_picture,
          expressive_label: res.expressive_label,
          avatar_action: res.avatar_action,
          tools_used: res.tools_used,
          model: res.model,
          created_at: res.created_at,
        });
        speakText(res.content);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to send message");
        setVoiceState("listening");
      } finally {
        setThinking(false);
      }
    },
    [isThinking, conversationId, isDeafened, channelId, channelForRuntime, voiceBrainSessionId]
  );

  // Keep ref in sync for VAD interval (avoids stale closure)
  handleSendRef.current = handleSend;

  const receiveBrainMessage = useCallback((res: ChatResponse) => {
    if (destroyedRef.current || !res?.content) return;
    setConversationId(channelId, res.conversation_id);
    if (res.emotion) setChatEmotion(res.emotion);
    setExpressiveLabel(res.expressive_label ?? null);
    setAvatarAction(res.avatar_action ?? null);
    addMessage(channelId, {
      id: res.message_id,
      role: "assistant",
      content: res.content,
      emotion: res.emotion,
      character_profile_id: res.character_profile_id,
      character_name: res.character_name,
      character_profile_picture: res.character_profile_picture,
      expressive_label: res.expressive_label,
      avatar_action: res.avatar_action,
      tools_used: res.tools_used,
      model: res.model,
      created_at: res.created_at,
    });
    setThinking(false);
    void speakTextRef.current(res.content);
  }, [addMessage, channelId, setAvatarAction, setChatEmotion, setConversationId, setExpressiveLabel, setThinking]);

  // =========================================================================
  // Backend-owned autonomous voice brain
  // =========================================================================
  useEffect(() => {
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connectSocket = () => {
      if (disposed) return;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(
        `${protocol}//${window.location.host}/api/ws/voice-brain/${encodeURIComponent(voiceBrainSessionId)}`,
      );
      brainSocketRef.current = socket;
      socket.onmessage = (event) => {
        try {
          const envelope = JSON.parse(event.data) as { type?: string; data?: unknown };
          if (envelope.type === "voice_brain_state") {
            setBrainStatus(envelope.data as VoiceBrainSessionStatus);
          } else if (envelope.type === "voice_brain_decision") {
            const decision = envelope.data as VoiceBrainDecision;
            setBrainDecision(decision);
            if (["SPEAK", "START_TOPIC", "ACT"].includes(decision.action)) {
              setVoiceState("thinking");
              setThinking(true);
            }
          } else if (envelope.type === "voice_brain_message") {
            receiveBrainMessage(envelope.data as ChatResponse);
          }
        } catch {
          // Ignore malformed diagnostic frames; voice operation continues.
        }
      };
      socket.onclose = () => {
        if (!disposed) reconnectTimer = setTimeout(connectSocket, 1500);
      };
    };

    void openVoiceBrainSession({
      session_id: voiceBrainSessionId,
      surface: "web_voice",
      channel_key: channelId,
      conversation_id: conversationIdRef.current,
      master_preset_id: channelForRuntime?.masterPresetId,
      enabled: true,
      phase: voiceStateRef.current === "idle" ? "listening" : voiceStateRef.current,
    })
      .then((status) => {
        if (!disposed) {
          setBrainStatus(status);
          connectSocket();
        }
      })
      .catch((err) => {
        if (!disposed) setError(err instanceof Error ? err.message : "Voice brain could not start");
      });

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      brainSocketRef.current?.close();
      brainSocketRef.current = null;
      void closeVoiceBrainSession(voiceBrainSessionId);
    };
  }, [channelForRuntime?.masterPresetId, channelId, receiveBrainMessage, setError, setThinking, voiceBrainSessionId]);

  // =========================================================================
  // VAD — continuous voice activity detection
  // =========================================================================
  async function setupStreamingSTT(audioContext: AudioContext, source: MediaStreamAudioSourceNode) {
    if (sttConfig?.streaming_enabled === false || sttConfig?.provider === "faster_whisper") return false;
    try {
      await audioContext.audioWorklet.addModule("/audio/pcm-capture-processor.js");
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${protocol}//${window.location.host}/api/ws/stt-stream`);
      socket.binaryType = "arraybuffer";
      sttSocketRef.current = socket;
      streamingReadyRef.current = false;
      pcmBufferRef.current = new Float32Array(0);

      socket.onopen = () => {
        socket.send(JSON.stringify({
          type: "start",
          model: sttConfig?.model || "nemotron-3.5-asr-streaming-0.6b",
          language: sttConfig?.stream_language || "auto",
          sample_rate: 16000,
          chunk_ms: sttConfig?.stream_chunk_ms || 320,
        }));
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as { type?: string; text?: string; message?: string };
          if (message.type === "ready") {
            streamingReadyRef.current = true;
            if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
              try { mediaRecorderRef.current.stop(); } catch { /* compatibility recorder may already be stopping */ }
              mediaRecorderRef.current = null;
              chunksRef.current = [];
            }
            return;
          }
          if (message.type === "partial") {
            setPartialTranscript(message.text || "");
          } else if (message.type === "final") {
            const text = (message.text || "").trim();
            setPartialTranscript("");
            if (text && !isMuted && !destroyedRef.current) handleSendRef.current(text);
          } else if (message.type === "error") {
            console.warn("[STT] streaming unavailable:", message.message);
            streamingReadyRef.current = false;
          }
        } catch {
          // Ignore non-JSON sidecar diagnostics.
        }
      };
      socket.onerror = () => { streamingReadyRef.current = false; };
      socket.onclose = () => {
        streamingReadyRef.current = false;
        if (sttSocketRef.current === socket) sttSocketRef.current = null;
      };

      const node = new AudioWorkletNode(audioContext, "pcm-capture-processor");
      node.port.onmessage = (event: MessageEvent<Float32Array>) => {
        if (!sttSocketRef.current || sttSocketRef.current.readyState !== WebSocket.OPEN || !streamingReadyRef.current) return;
        const input = event.data;
        const previous = pcmBufferRef.current;
        const merged = new Float32Array(previous.length + input.length);
        merged.set(previous);
        merged.set(input, previous.length);
        const ratio = audioContext.sampleRate / 16000;
        const target = Math.max(1280, Math.round(16000 * (sttConfig?.stream_chunk_ms || 320) / 1000));
        const available = Math.floor(merged.length / ratio);
        const count = Math.floor(available / target) * target;
        if (count <= 0) {
          pcmBufferRef.current = merged;
          return;
        }
        const pcm = new Int16Array(count);
        for (let i = 0; i < count; i++) {
          const sourceIndex = Math.min(merged.length - 1, Math.floor(i * ratio));
          const sample = Math.max(-1, Math.min(1, merged[sourceIndex]));
          pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
        }
        const consumed = Math.floor(count * ratio);
        pcmBufferRef.current = merged.slice(consumed);
        sttSocketRef.current.send(pcm.buffer);
      };
      source.connect(node);
      const sink = audioContext.createGain();
      sink.gain.value = 0;
      node.connect(sink).connect(audioContext.destination);
      workletNodeRef.current = node;
      return true;
    } catch (error) {
      console.warn("[STT] AudioWorklet streaming setup failed; using batch fallback", error);
      streamingReadyRef.current = false;
      return false;
    }
  }

  function startListening() {
    if (streamRef.current) return; // already listening

    navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
      if (destroyedRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;

      // Set up Web Audio API for volume analysis
      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyserRef.current = analyser;

      setVoiceState("listening");
      setIsMuted(false);

      // Start realtime PCM streaming; the recorder remains a compatibility
      // fallback when the sidecar/browser worklet is unavailable.
      void setupStreamingSTT(audioContext, source).then((streaming) => {
        if (!streaming && !destroyedRef.current && streamRef.current) startNewUtteranceRecorder(stream);
      });

      // Start VAD polling — uses getByteTimeDomainData (waveform, 128=silence)
      const dataArray = new Uint8Array(analyser.fftSize);
      vadIntervalRef.current = setInterval(() => {
        if (destroyedRef.current) {
          clearInterval(vadIntervalRef.current!);
          vadIntervalRef.current = null;
          return;
        }
        analyser.getByteTimeDomainData(dataArray);

        // Calculate RMS deviation from center (128)
        let sumSq = 0;
        for (let i = 0; i < dataArray.length; i++) {
          const deviation = dataArray[i] - 128;
          sumSq += deviation * deviation;
        }
        const rms = Math.sqrt(sumSq / dataArray.length);
        setVolumeLevel(rms);

        // Debug: log every ~1 second
        if (Math.random() < 0.02) {
          console.log("[VAD] volume:", rms.toFixed(1), "state:", voiceStateRef.current);
        }

        const currentState = voiceStateRef.current;
        const now = Date.now();

        if (currentState === "speaking") {
          // --- Barge-in: user talks while AI is speaking ---
          if (rms > BARGE_IN_THRESHOLD) {
            console.log("[VAD] Barge-in triggered, rms=", rms.toFixed(1));
            stopSpeaking();
            // Start recording the interruption
            isUserSpeakingRef.current = true;
            speechStartRef.current = now;
            silenceStartRef.current = 0;
            chunksRef.current = [];
            if (!streamingReadyRef.current) startNewUtteranceRecorder(stream);
            setVoiceState("user_speaking");
          }
          return;
        }

        if (currentState === "thinking" || currentState === "processing") {
          // Don't process VAD while waiting for LLM
          return;
        }

        if (rms > SPEECH_THRESHOLD) {
          // --- User is speaking ---
          if (!isUserSpeakingRef.current) {
            console.log("[VAD] Speech detected, rms=", rms.toFixed(1));
            isUserSpeakingRef.current = true;
            speechStartRef.current = now;
            silenceStartRef.current = 0;
            chunksRef.current = [];
            if (!streamingReadyRef.current) startNewUtteranceRecorder(stream);
            setVoiceState("user_speaking");
          }
          silenceStartRef.current = 0;
        } else if (rms < SILENCE_THRESHOLD) {
          // --- Silence ---
          if (isUserSpeakingRef.current) {
            if (silenceStartRef.current === 0) {
              silenceStartRef.current = now;
            }

            const silenceDuration = now - silenceStartRef.current;
            const speechDuration = now - speechStartRef.current;

            if (silenceDuration >= SILENCE_TIMEOUT_MS && speechDuration >= MIN_SPEECH_MS) {
              // User stopped talking — send accumulated audio to STT
              console.log("[VAD] Silence detected after", speechDuration, "ms of speech");
              isUserSpeakingRef.current = false;
              silenceStartRef.current = 0;
              if (streamingReadyRef.current) flushStreamingRef.current();
              else processRecordedAudioRef.current();
            }
          }
        }
      }, VAD_POLL_MS);
    }).catch((err) => {
      console.error("[VAD] Mic access denied:", err);
      setError("Microphone access denied");
    });
  }

  function startNewUtteranceRecorder(stream: MediaStream) {
    // Stop old recorder if any
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }

    // Start a fresh recorder for this utterance
    const mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
    chunksRef.current = [];
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    mediaRecorderRef.current = mediaRecorder;
    mediaRecorder.start();
  }

  function stopListening() {
    if (vadIntervalRef.current) {
      clearInterval(vadIntervalRef.current);
      vadIntervalRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    if (sttSocketRef.current) {
      try { sttSocketRef.current.send(JSON.stringify({ type: "stop" })); } catch { /* already closed */ }
      sttSocketRef.current.close();
      sttSocketRef.current = null;
    }
    workletNodeRef.current?.disconnect();
    workletNodeRef.current = null;
    streamingReadyRef.current = false;
    pcmBufferRef.current = new Float32Array(0);
    setPartialTranscript("");
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    analyserRef.current = null;
    mediaRecorderRef.current = null;
    chunksRef.current = [];
    isUserSpeakingRef.current = false;
  }

  function flushStreaming() {
    if (!sttSocketRef.current || sttSocketRef.current.readyState !== WebSocket.OPEN) {
      setVoiceState("listening");
      return;
    }
    setVoiceState("processing");
    sttSocketRef.current.send(JSON.stringify({ type: "flush" }));
    // Endpointing normally returns a final event. This timeout only prevents
    // a stuck status when a sidecar is restarted mid-utterance.
    window.setTimeout(() => {
      if (!destroyedRef.current && voiceStateRef.current === "processing") setVoiceState("listening");
    }, 2500);
  }

  flushStreamingRef.current = flushStreaming;

  function exitLiveMode() {
    try {
      stopListening();
    } catch {
      // Continue closing the view even if a browser media API fails.
    }
    if (channelForRuntime?.kind === "voice" || activeChannel === LIVE_CHANNEL) setActiveChannel("general");
    setLiveMode(false);
  }

  async function processRecordedAudio() {
    if (destroyedRef.current) return;
    if (chunksRef.current.length === 0) {
      console.log("[VAD] No audio chunks to process");
      setVoiceState("listening");
      return;
    }

    setVoiceState("processing");

    // Stop the recorder and collect the blob
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      // Request data one more time, then stop
      recorder.stop();
    }

    // Small delay to ensure ondataavailable fires for final chunk
    await new Promise((r) => setTimeout(r, 100));
    if (destroyedRef.current) return;

    const blob = new Blob(chunksRef.current, { type: "audio/webm" });
    chunksRef.current = [];

    console.log("[VAD] Audio blob size:", blob.size, "bytes");

    if (blob.size < 1000) {
      console.log("[VAD] Audio too small, skipping");
      setVoiceState("listening");
      // Restart recorder for next utterance
      if (!destroyedRef.current && streamRef.current) startNewUtteranceRecorder(streamRef.current);
      return;
    }

    try {
      const text = await fetchSTT(blob, channelForRuntime?.masterPresetId);
      if (destroyedRef.current) return;
      console.log("[VAD] STT result:", text);
      if (text && text.trim()) {
        handleSendRef.current(text);
      } else {
        setVoiceState("listening");
        if (streamRef.current) startNewUtteranceRecorder(streamRef.current);
      }
    } catch (err) {
      if (destroyedRef.current) return;
      console.error("[VAD] STT error:", err);
      setVoiceState("listening");
      if (streamRef.current) startNewUtteranceRecorder(streamRef.current);
    }
  }

  // Keep ref in sync for VAD interval (avoids stale closure)
  processRecordedAudioRef.current = processRecordedAudio;

  // =========================================================================
  // Voice-brain heartbeat — the backend owns timing and decisions
  // =========================================================================
  useEffect(() => {
    if (brainHeartbeatRef.current) {
      clearInterval(brainHeartbeatRef.current);
      brainHeartbeatRef.current = null;
    }
    const beat = () => {
      const phase = isMutedRef.current || isDeafened ? "idle" : voiceStateRef.current;
      void heartbeatVoiceBrainSession(voiceBrainSessionId, {
        phase,
        conversation_id: conversationIdRef.current,
        enabled: brainEnabled,
      }).then(setBrainStatus).catch(() => undefined);
    };
    beat();
    brainHeartbeatRef.current = setInterval(beat, 3000);

    return () => {
      if (brainHeartbeatRef.current) clearInterval(brainHeartbeatRef.current);
      brainHeartbeatRef.current = null;
    };
  }, [brainEnabled, isDeafened, voiceBrainSessionId]);

  // =========================================================================
  // Mute/Unmute
  // =========================================================================
  function toggleMute() {
    if (isMuted) {
      // Unmute — start listening
      startListening();
    } else {
      // Mute — stop recording but let in-progress work finish
      if (vadIntervalRef.current) {
        clearInterval(vadIntervalRef.current);
        vadIntervalRef.current = null;
      }
      // Stop MediaRecorder if active
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        mediaRecorderRef.current.stop();
      }
      if (sttSocketRef.current) {
        try { sttSocketRef.current.send(JSON.stringify({ type: "stop" })); } catch { /* ignore */ }
        sttSocketRef.current.close();
        sttSocketRef.current = null;
      }
      workletNodeRef.current?.disconnect();
      workletNodeRef.current = null;
      streamingReadyRef.current = false;
      pcmBufferRef.current = new Float32Array(0);
      setPartialTranscript("");
      // Close stream to free mic
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
      if (audioContextRef.current) {
        audioContextRef.current.close();
        audioContextRef.current = null;
      }
      analyserRef.current = null;
      mediaRecorderRef.current = null;
      // There is no in-flight batch request for realtime streams. Clear any
      // compatibility chunks so mute can never submit stale speech.
      chunksRef.current = [];
      isUserSpeakingRef.current = false;
      setIsMuted(true);
      setVolumeLevel(0);
      // Mute is an explicit hard stop for microphone state. Existing AI audio
      // may finish, but no listening/speaking indicator is allowed to return.
      setVoiceState("idle");
    }
  }

  // =========================================================================
  // Chat sidebar send
  // =========================================================================
  function handleChatSend() {
    const msg = chatInput.trim();
    if (!msg || isThinking) return;
    setChatInput("");
    handleSend(msg);
  }

  // =========================================================================
  // Derived state
  // =========================================================================
  const statusText = (() => {
    if (isMuted) return "Mic muted";
    switch (voiceState) {
      case "thinking": return "Thinking...";
      case "speaking": return "Speaking...";
      case "user_speaking": return "Hearing you...";
      case "processing": return "Processing...";
      case "listening": return "Listening...";
      default: return "Voice Connected";
    }
  })();

  const currentAiCaption = voiceState === "speaking" ? spokenText.trim() : "";

  // =========================================================================
  // Auto-start listening on mount
  // =========================================================================
  useEffect(() => {
    sfxConnect();
    if (!isMuted) {
      startListening();
    }
  }, []);

  // =========================================================================
  // Render
  // =========================================================================
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#1e1f22] overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center justify-between h-12 px-4 border-b border-[#3f4147]/50 shrink-0">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#23a55a]/15">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z"
                fill="#23a55a"
              />
              <path
                d="M19 11a7 7 0 0 1-14 0"
                stroke="#23a55a"
                strokeWidth="2"
                strokeLinecap="round"
              />
              <line x1="12" y1="18" x2="12" y2="21" stroke="#23a55a" strokeWidth="2" strokeLinecap="round" />
              <line x1="8" y1="21" x2="16" y2="21" stroke="#23a55a" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <span className="text-xs font-medium text-[#23a55a]">Voice Connected</span>
          </div>
          <button
            onClick={() => setBrainEnabled((value) => !value)}
            className={`flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] transition-colors ${
              brainEnabled && brainStatus?.enabled !== false
                ? "bg-[#5865f2]/15 text-[#8ea1e1] hover:bg-[#5865f2]/25"
                : "bg-[#3b3d44] text-[#6d6f78] hover:text-[#b5bac1]"
            }`}
            title={brainDecision?.reason || "Toggle autonomous voice decisions for this live room"}
          >
            <Brain size={12} />
            <span>
              {brainEnabled && brainStatus?.enabled !== false
                ? `Autonomy · ${brainStatus?.phase || "starting"}`
                : "Autonomy off"}
            </span>
          </button>
          <span className="text-xs text-[#949ba4]">/ {displayCharacterName()}</span>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowChat(!showChat)}
            className={`p-1.5 rounded transition-colors ${
              showChat
                ? "text-[#dbdee1] bg-[#3b3d44]"
                : "text-[#b5bac1] hover:text-[#dbdee1] hover:bg-[#35373c]"
            }`}
            title="Toggle chat"
          >
            <MessageSquare size={18} />
          </button>
          <button
            onClick={exitLiveMode}
            className="p-1.5 rounded text-[#b5bac1] hover:text-[#dbdee1] hover:bg-[#35373c] transition-colors"
            title="Disconnect"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      {/* Main content area */}
      <div className="flex-1 flex min-h-0 min-w-0">
        {/* Center */}
        <div className="flex-1 min-w-0 flex flex-col items-center justify-center relative">
          {/* Single AI caption — only shown while the character is speaking */}
          {currentAiCaption && (
            <div
              className="absolute top-6 left-1/2 z-10 w-[min(90%,42rem)] -translate-x-1/2 px-4 pointer-events-none"
              aria-live="polite"
              aria-atomic="true"
            >
              <div className="max-h-32 max-w-full overflow-y-auto overflow-x-hidden rounded-xl border border-[#3f4147]/70 bg-[#2b2d31]/90 px-4 py-3 text-center text-sm leading-6 text-[#dbdee1] shadow-lg backdrop-blur-sm whitespace-pre-wrap break-words [overflow-wrap:anywhere] animate-in fade-in slide-in-from-bottom-1">
                {currentAiCaption}
              </div>
            </div>
          )}

          {/* Volume indicator bar */}
          {!isMuted && voiceState === "user_speaking" && (
            <div className="absolute top-20 left-1/2 -translate-x-1/2 w-48 h-1.5 bg-[#1e1f22] rounded-full overflow-hidden">
              <div
                className="h-full bg-[#23a55a] rounded-full transition-all duration-75"
                style={{ width: `${Math.min(100, (volumeLevel / 40) * 100)}%` }}
              />
            </div>
          )}

          {/* Avatar display — model or orb */}
          <div className="relative w-64 h-80">
            <div
              className={`absolute -inset-3 rounded-2xl transition-all duration-300 ${
                isMuted
                  ? ""
                  : voiceState === "speaking"
                  ? "ring-4 ring-[#23a55a]/60 animate-pulse"
                  : voiceState === "thinking"
                  ? "ring-2 ring-[#f0b232]/30 animate-pulse"
                  : voiceState === "user_speaking"
                  ? "ring-2 ring-[#5865f2]/40"
                  : voiceState === "listening"
                  ? "ring-1 ring-[#5865f2]/20"
                  : ""
              }`}
            />
            {displayedAvatarMode === "model" ? (
              <Live2DCanvas
                modelPath={displayedAvatarModel}
                idlePreset={displayedIdlePreset}
                idleIntensity={displayedIdleIntensity}
                audioElement={!isMuted ? ttsAudio : null}
                lipSync={true}
                voiceState={isMuted ? "idle" : voiceState}
                showThinking={!isMuted && voiceState === "thinking"}
                className="rounded-2xl"
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center">
                <OrbAnimation
                  isThinking={voiceState === "thinking"}
                  isSpeaking={voiceState === "speaking"}
                  isListening={voiceState === "listening"}
                  emotion={character?.dominant_emotion}
                />
              </div>
            )}
          </div>

          {/* Avatar mode toggle */}
          <div className="flex items-center gap-1 mt-2">
            <button
              disabled={Boolean(channelRuntimeSettings)}
              onClick={() => { sfxClick(); setAvatarMode("model"); }}
              className={`px-2 py-0.5 rounded text-[10px] transition-colors ${
                displayedAvatarMode === "model"
                  ? "bg-[#5865f2]/20 text-[#5865f2]"
                  : "text-[#949ba4] hover:text-[#dbdee1]"
              }`}
            >
              Model
            </button>
            <button
              disabled={Boolean(channelRuntimeSettings)}
              onClick={() => { sfxClick(); setAvatarMode("orb"); }}
              className={`px-2 py-0.5 rounded text-[10px] transition-colors ${
                displayedAvatarMode === "orb"
                  ? "bg-[#5865f2]/20 text-[#5865f2]"
                  : "text-[#949ba4] hover:text-[#dbdee1]"
              }`}
            >
              Orb
            </button>
          </div>

          {/* Name */}
          <h2 className="text-xl font-semibold text-[#f2f3f5] mt-4">
            {displayCharacterName()}
          </h2>

          {/* Status */}
          <p className="text-xs text-[#949ba4] mt-1">{statusText}</p>
          {!isMuted && partialTranscript.trim() && (
            <div className="mt-3 max-w-[min(90vw,32rem)] rounded-lg border border-[#5865f2]/30 bg-[#2b2d31]/70 px-3 py-2 text-center text-xs leading-5 text-[#b5bac1] whitespace-pre-wrap break-words [overflow-wrap:anywhere]" aria-live="polite">
              {partialTranscript}
            </div>
          )}
        </div>

        {/* Chat sidebar */}
        <div
          className={`h-full min-w-0 max-w-full border-l border-[#3f4147]/50 bg-[#2b2d31]/95 backdrop-blur-md flex flex-col transition-all duration-300 overflow-hidden ${
            showChat ? "w-80" : "w-0"
          }`}
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-[#3f4147]/50 shrink-0">
            <h3 className="text-sm font-semibold text-[#f2f3f5]">Chat</h3>
            <button
              onClick={() => setShowChat(false)}
              className="p-1 rounded text-[#b5bac1] hover:text-[#dbdee1] hover:bg-[#35373c] transition-colors"
            >
              <X size={14} />
            </button>
          </div>

          <div className="flex-1 min-w-0 w-full overflow-y-auto overflow-x-hidden px-3 py-3 space-y-1">
            {msgs.map((m, i) => {
              const isUser = m.role === "user";
              const senderKey = isUser ? "user" : `assistant:${displayCharacterKey(m)}`;
              const previous = msgs[i - 1];
              const previousKey = previous
                ? previous.role === "user"
                  ? "user"
                  : `assistant:${displayCharacterKey(previous)}`
                : "";
              const showHeader = i === 0 || previousKey !== senderKey;
              const senderName = displayCharacterName(m);
              const senderPicture = displayCharacterPicture(m);

              return (
                <div
                  key={m.id}
                  className={`group w-full min-w-0 rounded-lg px-2 py-1.5 hover:bg-[#2e3035] ${
                    showHeader ? "mt-3" : ""
                  }`}
                >
                  {showHeader ? (
                    <div className="flex min-w-0 items-start gap-3">
                      <div
                        className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                          isUser ? "bg-[#5865f2]" : "bg-[#ed4245]"
                        }`}
                      >
                        {isUser ? <span className="text-xs font-bold text-white">Y</span> : senderPicture ? <img src={senderPicture} alt={senderName} className="h-full w-full rounded-full object-cover" /> : <span className="text-xs font-bold text-white">{senderName[0] ?? "A"}</span>}
                      </div>
                      <div className="flex-1 min-w-0 max-w-full">
                        <div className="flex items-baseline gap-2">
                          <span
                            className={`text-xs font-medium ${
                              isUser ? "text-[#5865f2]" : "text-[#ed4245]"
                            }`}
                          >
                            {isUser ? "You" : senderName}
                          </span>
                          <span className="text-[10px] text-[#949ba4]">
                            {m.created_at
                              ? new Date(m.created_at).toLocaleTimeString([], {
                                  hour: "2-digit",
                                  minute: "2-digit",
                                })
                              : ""}
                          </span>
                        </div>
                        <p className="max-w-full break-words text-sm leading-relaxed text-[#dbdee1] whitespace-pre-wrap [overflow-wrap:anywhere]">
                          {m.content}
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div className="flex min-w-0 items-start gap-3">
                      <div className="w-8 shrink-0" />
                      <p className="min-w-0 max-w-full flex-1 break-words text-sm leading-relaxed text-[#dbdee1] whitespace-pre-wrap [overflow-wrap:anywhere]">
                        {m.content}
                      </p>
                    </div>
                  )}
                  <ToolCallIndicators tools={m.tools_used} className="ml-11 mt-1" />
                </div>
              );
            })}

            {(isThinking || voiceState === "thinking") && (
              <div className="group w-full min-w-0 rounded-lg px-2 py-1.5 hover:bg-[#2e3035] mt-3">
                <div className="flex min-w-0 items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-[#ed4245] flex items-center justify-center shrink-0">
                    {displayCharacterPicture() ? <img src={displayCharacterPicture()} alt={displayCharacterName()} className="h-full w-full rounded-full object-cover" /> : <span className="text-xs font-bold text-white">{displayCharacterName()[0] ?? "A"}</span>}
                  </div>
                  <div className="flex items-center gap-2 pt-1.5">
                    <div className="flex gap-1">
                      <span className="w-1.5 h-1.5 bg-[#949ba4] rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                      <span className="w-1.5 h-1.5 bg-[#949ba4] rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                      <span className="w-1.5 h-1.5 bg-[#949ba4] rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                    </div>
                    <span className="text-xs text-[#949ba4]">is typing...</span>
                  </div>
                </div>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          {/* Chat input */}
          <div className="px-3 pb-3 shrink-0">
            <div className="flex items-center bg-[#383a40] rounded-lg">
              <input
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleChatSend();
                  }
                }}
                placeholder={`Message #${displayCharacterName()}`}
                className="flex-1 bg-transparent px-3 py-2.5 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none"
              />
              <button
                onClick={handleChatSend}
                disabled={!chatInput.trim()}
                className="p-2.5 text-[#b5bac1] hover:text-[#dbdee1] disabled:text-[#4e5058] transition-colors"
              >
                <Send size={16} />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom controls bar */}
      <div className="h-20 border-t border-[#3f4147]/50 flex items-center justify-center gap-4 shrink-0 bg-[#232428]">
        {/* Mic — toggle listening */}
        <button
          onClick={toggleMute}
          className={`w-12 h-12 rounded-full flex items-center justify-center transition-colors ${
            isMuted
              ? "bg-[#f23f43] text-white hover:bg-[#f23f43]/80"
              : voiceState === "user_speaking"
              ? "bg-[#5865f2] text-white"
              : voiceState === "listening"
              ? "bg-[#23a55a] text-white"
              : "bg-[#2b2d31] text-[#b5bac1] hover:bg-[#35373c] hover:text-[#dbdee1]"
          }`}
          title={isMuted ? "Unmute" : "Mute"}
        >
          {isMuted ? <MicOff size={20} /> : <Mic size={20} />}
        </button>

        {/* Deafen */}
        <button
          onClick={() => {
            setIsDeafened(!isDeafened);
            if (!isDeafened) stopSpeaking();
          }}
          className={`w-12 h-12 rounded-full flex items-center justify-center transition-colors ${
            isDeafened
              ? "bg-[#f23f43] text-white hover:bg-[#f23f43]/80"
              : "bg-[#2b2d31] text-[#b5bac1] hover:bg-[#35373c] hover:text-[#dbdee1]"
          }`}
          title={isDeafened ? "Undeafen" : "Deafen"}
        >
          {isDeafened ? <HeadphoneOff size={20} /> : <Headphones size={20} />}
        </button>

        {/* Share screen (decorative) */}
        <button
          className="w-12 h-12 rounded-full flex items-center justify-center bg-[#2b2d31] text-[#b5bac1] hover:bg-[#35373c] hover:text-[#dbdee1] transition-colors"
          title="Share Screen"
        >
          <ScreenShare size={20} />
        </button>

        {/* Disconnect */}
        <button
          onClick={exitLiveMode}
          className="w-12 h-12 rounded-full flex items-center justify-center bg-[#f23f43] text-white hover:bg-[#f23f43]/80 transition-colors"
          title="Disconnect"
        >
          <PhoneOff size={20} />
        </button>
      </div>
    </div>
  );
}
