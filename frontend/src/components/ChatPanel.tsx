import { useCallback, useEffect, useRef, useState } from "react";
import { useAppStore } from "../stores/appStore";
import { fetchSTT, fetchTTS, sendChat, sendVoiceMessage } from "../lib/api";
import {
  Mic,
  MicOff,
  Volume2,
  VolumeX,
  PlusCircle,
  Send,
  Loader2,
  X,
  Play,
} from "lucide-react";
import { SmartBar } from "./SmartBar";
import { ToolCallIndicators } from "./ToolCallIndicators";
import { resolveChannelMasterPreset } from "../lib/channelRuntime";
import { sfxClick, sfxError, sfxMessage } from "../lib/sounds";

type VoiceMode = "off" | "stt" | "voice";

export function ChatPanel() {
  const activeChannel = useAppStore((s) => s.activeChannel);
  const messages = useAppStore((s) => s.channelMessages[s.activeChannel]);
  const isThinking = useAppStore((s) => s.isThinking);
  const addMessage = useAppStore((s) => s.addMessage);
  const setConversationId = useAppStore((s) => s.setConversationId);
  const setThinking = useAppStore((s) => s.setThinking);
  const setError = useAppStore((s) => s.setError);
  const setChatEmotion = useAppStore((s) => s.setChatEmotion);
  const setExpressiveLabel = useAppStore((s) => s.setExpressiveLabel);
  const setAvatarAction = useAppStore((s) => s.setAvatarAction);
  const character = useAppStore((s) => s.character);
  const voiceEnabled = useAppStore((s) => s.voiceEnabled);
  const setVoiceEnabled = useAppStore((s) => s.setVoiceEnabled);
  const setChannelSpeech = useAppStore((s) => s.setChannelSpeech);
  const clearChannelSpeech = useAppStore((s) => s.clearChannelSpeech);
  const conversationId = useAppStore((s) => s.channelConversations[s.activeChannel]);
  const channels = useAppStore((s) => s.channels);
  const channel = channels.find((item) => item.id === activeChannel);
  const channelRuntimeSettings = useAppStore((s) => s.channelRuntimeSettings[activeChannel]);
  const settingsPersisted = useAppStore((s) => s.settingsPersisted);

  const msgs = messages ?? [];

  const currentProfileId = settingsPersisted?.character_profile_id || character?.profile_id;
  const currentProfileName = settingsPersisted?.character_name || character?.name;
  const displayCharacterName = (message?: { character_profile_id?: string | null; character_name?: string | null }) => {
    // Historical messages carry a profile ID. Prefer the current saved name
    // for that same profile so a rename is reflected immediately in an open
    // chat; messages from other personas retain their own snapshot.
    if (message?.character_profile_id && currentProfileId && message.character_profile_id === currentProfileId && currentProfileName) {
      return currentProfileName;
    }
    return message?.character_name || channelRuntimeSettings?.character_name || currentProfileName || "Aiko";
  };
  const displayCharacterPicture = (message?: { character_profile_picture?: string | null }) => message?.character_profile_picture || channelRuntimeSettings?.character_profile_picture || character?.profile_picture || "";
  const displayCharacterKey = (message?: { character_profile_id?: string | null; character_name?: string | null; character_profile_picture?: string | null }) =>
    message?.character_profile_id || message?.character_name || message?.character_profile_picture || channelRuntimeSettings?.character_profile_id || character?.profile_id || character?.name || "AI";

  const [input, setInput] = useState("");
  const [voiceMode, setVoiceMode] = useState<VoiceMode>("off");
  const [isRecording, setIsRecording] = useState(false);
  const [recordingDuration, setRecordingDuration] = useState(0);
  const [voiceBlob, setVoiceBlob] = useState<Blob | null>(null);
  const [voiceUrl, setVoiceUrl] = useState<string | null>(null);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const voiceUrlRef = useRef<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const recordingCancelledRef = useRef(false);
  const chunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<number | null>(null);
  voiceUrlRef.current = voiceUrl;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, isThinking]);

  useEffect(() => {
    const last = msgs[msgs.length - 1];
    if (last?.role === "user") stopSpeaking();
  }, [msgs]);

  // The TTS toggle is the single authority for channel speech. This also
  // stops playback when Voice/TTS is disabled from the header or SmartBar.
  useEffect(() => {
    if (!voiceEnabled) stopSpeaking();
  }, [voiceEnabled]);

  useEffect(() => {
    return () => {
      recordingCancelledRef.current = true;
      if (recordingTimerRef.current !== null) clearInterval(recordingTimerRef.current);
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") mediaRecorderRef.current.stop();
      recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
      if (audioRef.current) {
        audioRef.current.pause();
        clearChannelSpeech(audioRef.current);
      } else {
        clearChannelSpeech();
      }
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
      if (voiceUrlRef.current) URL.revokeObjectURL(voiceUrlRef.current);
    };
  }, []);

  function stopSpeaking() {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audioRef.current = null;
      clearChannelSpeech(audio);
    } else {
      clearChannelSpeech();
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    setIsSpeaking(false);
  }

  async function speakText(text: string) {
    if (!voiceEnabled) return;
    let audio: HTMLAudioElement | null = null;
    try {
      setIsSpeaking(true);
      setChannelSpeech(null, "processing");
      const blob = await fetchTTS(text, undefined, undefined, undefined, channel?.masterPresetId);
      const url = URL.createObjectURL(blob);
      audioUrlRef.current = url;
      audio = new Audio(url);
      audioRef.current = audio;
      setChannelSpeech(audio, "speaking");
      audio.onended = () => {
        if (audioRef.current === audio) audioRef.current = null;
        setIsSpeaking(false);
        clearChannelSpeech(audio ?? undefined);
        URL.revokeObjectURL(url);
        if (audioUrlRef.current === url) audioUrlRef.current = null;
      };
      audio.onerror = () => {
        if (audioRef.current === audio) audioRef.current = null;
        setIsSpeaking(false);
        clearChannelSpeech(audio ?? undefined);
        URL.revokeObjectURL(url);
        if (audioUrlRef.current === url) audioUrlRef.current = null;
      };
      await audio.play();
    } catch (err) {
      setIsSpeaking(false);
      if (audio) clearChannelSpeech(audio);
      else clearChannelSpeech();
      console.warn("TTS generation failed or unavailable:", err);
    }
  }

  const handleSend = useCallback(
    async (text?: string) => {
      const msg = (text ?? input).trim();
      if (!msg || isThinking) return;

      setInput("");
      stopSpeaking();
      await resolveChannelMasterPreset(channel);
      setAvatarAction({ emotion: "curiosity", gesture: "lean_in", intensity: 0.42, hold_ms: 900 });

      addMessage(activeChannel, {
        id: crypto.randomUUID(),
        role: "user",
        content: msg,
      });
      setThinking(true);
      setError(null);

      try {
        const res = await sendChat(msg, conversationId, channel?.masterPresetId);
        setConversationId(activeChannel, res.conversation_id);
        setChatEmotion(res.emotion);
        setExpressiveLabel(res.expressive_label ?? null);
        setAvatarAction(res.avatar_action ?? null);
        addMessage(activeChannel, {
          id: res.message_id,
          role: "assistant",
          content: res.content,
          emotion: res.emotion,
          expressive_label: res.expressive_label,
          avatar_action: res.avatar_action,
          tools_used: res.tools_used,
          character_profile_id: res.character_profile_id,
          character_name: res.character_name,
          character_profile_picture: res.character_profile_picture,
          model: res.model,
          created_at: res.created_at,
        });
        sfxMessage();
        speakText(res.content);
      } catch (err) {
        sfxError();
        setError(err instanceof Error ? err.message : "Failed to send message");
      } finally {
        setThinking(false);
      }
    },
    [input, isThinking, conversationId, voiceEnabled, activeChannel, channel]
  );

  const handleSendVoice = useCallback(async () => {
    if (!voiceBlob || isThinking) return;

    const sizeKb = Math.round(voiceBlob.size / 1024);
    addMessage(activeChannel, {
      id: crypto.randomUUID(),
      role: "user",
      content: `[Voice message • ${sizeKb} KB • ${Math.round(recordingDuration)}s]`,
      voiceBlob: voiceBlob,
      voiceUrl: voiceUrl || undefined,
    });
    setVoiceBlob(null);
    setVoiceUrl(null);
    setRecordingDuration(0);
    stopSpeaking();
    setAvatarAction({ emotion: "curiosity", gesture: "lean_in", intensity: 0.5, hold_ms: 1100 });

    setThinking(true);
    setError(null);

    try {
      await resolveChannelMasterPreset(channel);
      const res = await sendVoiceMessage(voiceBlob, conversationId, channel?.masterPresetId);
      setConversationId(activeChannel, res.conversation_id);
      setChatEmotion(res.emotion);
      setExpressiveLabel(res.expressive_label ?? null);
      setAvatarAction(res.avatar_action ?? null);
      addMessage(activeChannel, {
        id: res.message_id,
        role: "assistant",
        content: res.content,
        emotion: res.emotion,
        expressive_label: res.expressive_label,
        avatar_action: res.avatar_action,
        tools_used: res.tools_used,
        character_profile_id: res.character_profile_id,
        character_name: res.character_name,
        character_profile_picture: res.character_profile_picture,
        model: res.model,
        created_at: res.created_at,
      });
      speakText(res.content);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send voice message");
    } finally {
      setThinking(false);
    }
  }, [voiceBlob, voiceUrl, conversationId, isThinking, recordingDuration, channel]);

  const voiceModeRef = useRef<VoiceMode>(voiceMode);
  voiceModeRef.current = voiceMode;

  function startRecording(targetMode?: VoiceMode) {
    if (isRecording) return;
    const currentMode = targetMode || voiceModeRef.current;
    chunksRef.current = [];
    recordingCancelledRef.current = false;

    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((stream) => {
        if (recordingCancelledRef.current) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        const mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
        recordingStreamRef.current = stream;

        mediaRecorder.ondataavailable = (e) => {
          if (!recordingCancelledRef.current && e.data.size > 0) chunksRef.current.push(e.data);
        };

        mediaRecorder.onstop = async () => {
          stream.getTracks().forEach((t) => t.stop());
          if (recordingStreamRef.current === stream) recordingStreamRef.current = null;
          if (recordingCancelledRef.current) {
            chunksRef.current = [];
            return;
          }
          const blob = new Blob(chunksRef.current, { type: "audio/webm" });
          if (blob.size < 1000) {
            setError("Recording too short");
            return;
          }

          if (currentMode === "stt") {
            try {
              setError(null);
              const text = await fetchSTT(blob, channel?.masterPresetId);
              if (text && text.trim()) {
                setInput((prev) => (prev ? `${prev} ${text.trim()}` : text.trim()));
              }
            } catch (err) {
              setError(err instanceof Error ? err.message : "Failed to transcribe speech");
            }
          } else {
            const url = URL.createObjectURL(blob);
            setVoiceBlob(blob);
            setVoiceUrl(url);
          }
        };

        mediaRecorderRef.current = mediaRecorder;
        mediaRecorder.start();
        setIsRecording(true);

        const startTime = Date.now();
        recordingTimerRef.current = window.setInterval(() => {
          setRecordingDuration((Date.now() - startTime) / 1000);
        }, 100);

        stopSpeaking();
      })
      .catch(() => {
        setError("Microphone access denied");
      });
  }

  function stopRecording() {
    if (recordingTimerRef.current !== null) {
      clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
    if (isRecording && mediaRecorderRef.current) {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current = null;
      setIsRecording(false);
    }
  }

  function cancelRecording() {
    recordingCancelledRef.current = true;
    stopRecording();
    chunksRef.current = [];
    if (voiceUrl) URL.revokeObjectURL(voiceUrl);
    setVoiceBlob(null);
    setVoiceUrl(null);
    setRecordingDuration(0);
  }

  async function toggleRecording() {
    if (isRecording) {
      stopRecording();
      return;
    }

    if (voiceMode === "off") {
      setVoiceMode("stt");
      voiceModeRef.current = "stt";
      startRecording("stt");
    } else {
      startRecording();
    }
  }

  function cycleVoiceMode() {
    if (voiceMode === "off") {
      setVoiceMode("stt");
      setError(null);
    } else if (voiceMode === "stt") {
      setVoiceMode("voice");
      setError(null);
    } else {
      setVoiceMode("off");
      cancelRecording();
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (input.trim()) {
        handleSend();
      }
    }
    if (e.key === "Escape" && voiceBlob) {
      cancelRecording();
    }
  }

  function formatDuration(seconds: number) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  return (
    <div className="flex flex-col h-full bg-[#313338]">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-5 space-y-[1px]">
        {msgs.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-16 h-16 rounded-2xl bg-[#3f4147] border border-[#5865f2]/40 flex items-center justify-center mb-4">
              {character?.profile_picture ? <img src={character.profile_picture} alt={character.name} className="h-full w-full rounded-full object-cover" /> : <span className="text-3xl font-bold text-white">{character?.name?.[0] ?? "A"}</span>}
            </div>
            <h3 className="text-lg font-semibold text-[#f2f3f5] mb-1">
              Welcome to #{character?.name ?? "AI"}!
            </h3>
            <p className="text-sm text-[#949ba4]">
              This is the start of your conversation.
            </p>
          </div>
        )}

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
          const isVoice = m.voiceUrl && isUser;

          return (
            <div
              key={m.id}
              className={`group relative px-3 py-1 hover:bg-[#2b2d31] rounded-lg ${
                showHeader ? "mt-4" : ""
              }`}
            >
              {showHeader ? (
                <div className="flex items-start gap-4">
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
                      isUser ? "bg-[#3f4147] border border-[#5865f2]/40" : "bg-[#5865f2]"
                    }`}
                  >
                    {isUser ? <span className="text-sm font-bold text-white">Y</span> : senderPicture ? <img src={senderPicture} alt={senderName} className="h-full w-full rounded-full object-cover" /> : <span className="text-sm font-bold text-white">{senderName[0] ?? "A"}</span>}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span
                        className={`text-sm font-medium ${
                          isUser ? "text-[#b5bac1]" : "text-[#f2f3f5]"
                        }`}
                      >
                        {isUser ? "You" : senderName}
                      </span>
                        <span className="text-[10px] text-[#6d6f78]">
                        {m.created_at
                          ? new Date(m.created_at).toLocaleTimeString([], {
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          : ""}
                      </span>
                      {m.emotion && (
                        <span className="text-[10px] text-[#b5bac1] bg-[#3f4147] px-1.5 py-0.5 rounded">
                          {m.emotion}
                        </span>
                      )}
                      {!isUser && voiceEnabled && (
                        <button
                          onClick={() => speakText(m.content)}
                          className="opacity-0 group-hover:opacity-100 p-0.5 text-[#949ba4] hover:text-[#5865f2] transition-opacity ml-1 rounded"
                          title="Read aloud with TTS"
                        >
                          <Volume2 size={13} />
                        </button>
                      )}
                    </div>

                    {/* Voice message bubble */}
                    {isVoice && m.voiceUrl ? (
                      <div className="mt-1 flex items-center gap-2 max-w-md bg-[#3f4147] border border-[#5865f2]/40 rounded-lg px-3 py-2">
                        <Play size={16} className="text-white shrink-0" />
                        <audio
                          src={m.voiceUrl}
                          controls
                          className="h-8 flex-1"
                          style={{ filter: "invert(1) hue-rotate(180deg)" }}
                        />
                        <span className="text-[10px] text-white/80 shrink-0">
                          {m.content.match(/• ([\d.]+)s/)?.[1] || "?"}s
                        </span>
                      </div>
                    ) : (
                      <p className="text-sm text-[#dbdee1] leading-relaxed whitespace-pre-wrap">
                        {m.content}
                      </p>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-4">
                  <div className="w-10 shrink-0" />
                  {isVoice && m.voiceUrl ? (
                    <div className="flex items-center gap-2 max-w-md bg-[#3f4147] border border-[#5865f2]/40 rounded-lg px-3 py-2">
                      <Play size={16} className="text-white shrink-0" />
                      <audio
                        src={m.voiceUrl}
                        controls
                        className="h-8 flex-1"
                        style={{ filter: "invert(1) hue-rotate(180deg)" }}
                      />
                    </div>
                  ) : (
                    <p className="text-sm text-[#dbdee1] leading-relaxed whitespace-pre-wrap">
                      {m.content}
                    </p>
                  )}
                </div>
              )}

              <ToolCallIndicators tools={m.tools_used} className="ml-14 mt-1" />

              {/* Speaking indicator */}
              {isSpeaking && m.role === "assistant" && i === msgs.length - 1 && (
                <div className="flex items-center gap-1.5 mt-1 ml-14">
                  <div className="flex gap-0.5">
                    {[1, 2, 3, 4].map((j) => (
                      <span
                        key={j}
                        className="w-0.5 bg-[#5865f2] rounded-full animate-pulse"
                        style={{
                          height: `${6 + Math.sin(Date.now() / 200 + j) * 4}px`,
                          animationDelay: `${j * 100}ms`,
                        }}
                      />
                    ))}
                  </div>
                  <Volume2 size={12} className="text-[#5865f2]/60" />
                </div>
              )}
            </div>
          );
        })}

        {isThinking && (
          <div className="group relative px-3 py-1 hover:bg-[#2b2d31] rounded-lg mt-4">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-[#5865f2] flex items-center justify-center shrink-0">
                {character?.profile_picture ? <img src={character.profile_picture} alt={character.name} className="h-full w-full rounded-full object-cover" /> : <span className="text-sm font-bold text-white">{character?.name?.[0] ?? "A"}</span>}
              </div>
              <div className="flex items-center gap-2 pt-2">
                <Loader2 size={16} className="text-[#949ba4] animate-spin" />
                <span className="text-sm text-[#949ba4]">is typing...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="px-5 pb-5 pt-2 relative bg-[#2b2d31] border-t border-[#3a3d43]">
        {/* Voice preview bar */}
        {voiceBlob && voiceUrl && (
          <div className="mb-2 flex items-center gap-2 bg-[#232428] rounded-lg px-3 py-2 border border-[#5865f2]/50">
            <Mic size={16} className="text-[#5865f2]" />
            <audio
              src={voiceUrl}
              controls
              className="h-7 flex-1"
              style={{ filter: "invert(1) hue-rotate(180deg)" }}
            />
            <span className="text-[10px] text-[#949ba4] shrink-0">
              {formatDuration(recordingDuration)}
            </span>
            <button
              onClick={cancelRecording}
              title="Discard"
              className="p-1 rounded hover:bg-[#35373c] text-[#949ba4] hover:text-[#f23f43] transition-colors"
            >
              <X size={14} />
            </button>
            <button
              onClick={handleSendVoice}
              disabled={isThinking}
              title="Send voice message"
              className="px-3 py-1 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-medium transition-colors disabled:opacity-40 flex items-center gap-1"
            >
              <Send size={12} /> Send
            </button>
          </div>
        )}

        {/* Recording indicator */}
        {isRecording && (
          <div className="mb-2 flex items-center gap-2 bg-[#f23f43]/10 border border-[#f23f43] rounded-lg px-3 py-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#f23f43] opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-[#f23f43]"></span>
            </span>
            <span className="text-xs text-[#f23f43] font-medium">
              Recording... {formatDuration(recordingDuration)}
            </span>
            <span className="text-[10px] text-[#949ba4] ml-auto">
              {voiceMode === "voice"
                ? "Release mic to send as voice message"
                : "Release mic to transcribe"}
            </span>
          </div>
        )}

        {/* Text input */}
        <div className="flex items-center bg-[#1e1f22] border border-[#3a3d43] rounded-xl shadow-sm">
          <button
            className="p-3 text-[#b5bac1] hover:text-[#dbdee1] transition-colors"
            title="Add attachment (coming soon)"
            disabled
          >
            <PlusCircle size={22} />
          </button>

          <div className="flex-1 flex items-center">
            <SmartBar activeChannel={activeChannel} />
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={
                voiceMode === "voice"
                  ? "Voice messages will be sent as audio..."
                  : isRecording
                  ? "Listening..."
                  : `Message #${character?.name ?? "AI"}`
              }
              rows={1}
              className="flex-1 resize-none bg-transparent py-3 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none"
            />
          </div>

          <div className="flex items-center gap-0.5 pr-2">
            {/* Send button (text mode) */}
            {input.trim() && !voiceBlob && (
              <button
                onClick={() => { sfxClick(); handleSend(); }}
                disabled={isThinking}
                className="p-2 text-[#5865f2] hover:text-[#4752c4] transition-colors disabled:opacity-40"
                title="Send"
              >
                <Send size={18} />
              </button>
            )}

            {/* Mic button - cycles through modes */}
            <button
              onMouseDown={toggleRecording}
              onMouseUp={voiceMode === "stt" || voiceMode === "voice" ? stopRecording : undefined}
              onMouseLeave={voiceMode === "stt" || voiceMode === "voice" ? stopRecording : undefined}
              title={
                voiceMode === "voice"
                  ? "Hold to record voice message"
                  : voiceMode === "stt"
                  ? "Hold to record (transcribe)"
                  : "Click to enable voice"
              }
              className={`p-2 rounded transition-colors ${
                isRecording
                  ? "text-[#f23f43] bg-[#f23f43]/10"
                  : voiceMode !== "off"
                  ? "text-[#5865f2]"
                  : "text-[#b5bac1] hover:text-[#dbdee1]"
              }`}
            >
              {isRecording ? <MicOff size={20} /> : <Mic size={20} />}
            </button>

            {/* Voice mode cycle button */}
            <button
              onClick={cycleVoiceMode}
              title={`Voice mode: ${voiceMode}`}
              className={`p-2 rounded transition-colors text-[10px] font-bold ${
                voiceMode === "voice"
                  ? "text-[#5865f2]"
                  : voiceMode === "stt"
                  ? "text-[#949ba4]"
                  : "text-[#6d6f78] hover:text-[#949ba4]"
              }`}
            >
              {voiceMode === "voice" ? "VC" : voiceMode === "stt" ? "STT" : "OFF"}
            </button>

            {/* Voice output toggle */}
            <button
              onClick={() => {
                if (voiceEnabled) stopSpeaking();
                setVoiceEnabled(!voiceEnabled);
              }}
              title={voiceEnabled ? "TTS Voice Output: ENABLED (Click to mute)" : "TTS Voice Output: DISABLED (Click to enable)"}
              className={`flex items-center gap-1 px-2 py-1 rounded transition-colors text-xs font-semibold ${
                voiceEnabled
                  ? "text-[#5865f2] bg-[#5865f2]/15 border border-[#5865f2]/30"
                  : "text-[#949ba4] hover:text-[#dbdee1] bg-transparent"
              }`}
            >
              {voiceEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
              <span className="text-[10px] uppercase font-bold">{voiceEnabled ? "TTS ON" : "TTS OFF"}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
