import { useState } from "react";
import {
  Brain,
  HelpCircle,
  Type,
  BookOpen,
  Puzzle,
  Send,
  Loader2,
  Sparkles,
} from "lucide-react";

const GAMES: Record<string, { name: string; description: string; icon: React.ElementType; systemPrompt: string }> = {
  trivia: {
    name: "Trivia",
    description: "Test your knowledge with questions across various topics",
    icon: Brain,
    systemPrompt: "You are a trivia host. Ask me interesting trivia questions one at a time. Wait for my answer before telling me if I was right or wrong, then give me a score. Keep it fun and engaging.",
  },
  "20-questions": {
    name: "20 Questions",
    description: "Think of something and I'll try to guess it",
    icon: HelpCircle,
    systemPrompt: "You are playing 20 Questions. I will think of something, and you ask yes/no questions to guess what it is. You have 20 questions max. Be strategic with your questions.",
  },
  "word-game": {
    name: "Word Game",
    description: "Word association and vocabulary challenges",
    icon: Type,
    systemPrompt: "You are a word game host. Play word association, word chain, or other word games with me. Make it challenging but fun.",
  },
  story: {
    name: "Story Creator",
    description: "Create interactive stories together",
    icon: BookOpen,
    systemPrompt: "You are a creative storytelling partner. We will create stories together. Give me vivid descriptions and interesting choices. Make the story engaging and immersive.",
  },
  riddles: {
    name: "Riddles",
    description: "Solve riddles and brain teasers",
    icon: Puzzle,
    systemPrompt: "You are a riddle master. Give me riddles of varying difficulty. After I guess, reveal the answer and explain. Keep score of how many I get right.",
  },
};

interface GamesPanelProps {
  channelId?: string;
}

export function GamesPanel({ channelId }: GamesPanelProps) {
  const game = GAMES[channelId ?? "trivia"];
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Array<{ role: string; content: string }>>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [started, setStarted] = useState(false);

  if (!game) {
    return (
      <div className="flex flex-col h-full p-4">
        <p className="text-[#949ba4] text-sm">Select a game from the channel list.</p>
      </div>
    );
  }

  const Icon = game.icon;

  async function handleSend() {
    const msg = input.trim();
    if (!msg || isThinking) return;

    setInput("");
    const userMsg = { role: "user", content: msg };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setIsThinking(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: started ? msg : `${game.systemPrompt}\n\nUser: ${msg}`,
          character_name: "Game Master",
        }),
      });
      const data = await res.json();
      setMessages([...newMessages, { role: "assistant", content: data.content || data.detail }]);
      setStarted(true);
    } catch {
      setMessages([...newMessages, { role: "assistant", content: "Failed to get response. Is the server running?" }]);
    } finally {
      setIsThinking(false);
    }
  }

  function startGame() {
    setMessages([]);
    setStarted(false);
    setInput("");
  }

  return (
    <div className="flex flex-col h-full bg-[#313338]">
      {/* Game header */}
      <div className="p-4 border-b border-[#3a3d43] bg-[#2b2d31]">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-[#3f4147] border border-[#5865f2]/40 flex items-center justify-center">
            <Icon size={20} className="text-white" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">{game.name}</h3>
            <p className="text-xs text-[#949ba4]">{game.description}</p>
          </div>
          <button
            onClick={startGame}
            className="ml-auto px-3 py-1.5 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-medium transition-colors"
          >
            New Game
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-[1px]">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <Sparkles size={32} className="text-[#5865f2]/30 mb-3" />
            <p className="text-sm text-[#949ba4] mb-2">Ready to play {game.name}!</p>
            <p className="text-xs text-[#6d6f78]">Type a message to start</p>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`group px-4 py-0.5 hover:bg-[#2e3035] ${i === 0 || messages[i-1]?.role !== m.role ? "mt-4" : ""}`}>
            <div className="flex items-start gap-4">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
                m.role === "user" ? "bg-[#5865f2]" : "bg-[#ed4245]"
              }`}>
                <span className="text-sm font-bold text-white">
                  {m.role === "user" ? "Y" : "GM"}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className={`text-sm font-medium ${m.role === "user" ? "text-[#5865f2]" : "text-[#ed4245]"}`}>
                    {m.role === "user" ? "You" : "Game Master"}
                  </span>
                </div>
                <p className="text-sm text-[#dbdee1] leading-relaxed whitespace-pre-wrap">{m.content}</p>
              </div>
            </div>
          </div>
        ))}

        {isThinking && (
          <div className="flex items-center gap-2 px-4 py-2 mt-4">
            <Loader2 size={16} className="text-[#949ba4] animate-spin" />
            <span className="text-sm text-[#949ba4]">Game Master is thinking...</span>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="px-4 pb-6">
        <div className="flex items-center bg-[#1e1f22] border border-[#3a3d43] rounded-xl">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder={`Play ${game.name}...`}
            className="flex-1 bg-transparent px-4 py-3 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isThinking}
            className="p-3 text-[#b5bac1] hover:text-[#dbdee1] disabled:opacity-30 transition-colors"
          >
            <Send size={20} />
          </button>
        </div>
      </div>
    </div>
  );
}
