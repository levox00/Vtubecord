import { useEffect, useRef } from "react";
import { useAppStore } from "../stores/appStore";
import { backendWebSocketUrl } from "../lib/runtime";

/**
 * Connects to the backend bridge-events WebSocket and dispatches
 * Discord events (message_create, voice_state_update, etc.) to the store.
 */
export function useBridgeEvents() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(false);

  // Stable store selectors — these never change between renders
  const addBridgeMessage = useAppStore((s) => s.addBridgeMessage);
  const setBridgeVoiceState = useAppStore((s) => s.setBridgeVoiceState);
  const setBridgeConnected = useAppStore((s) => s.setBridgeConnected);
  const setBridgeDiscordConfig = useAppStore((s) => s.setBridgeDiscordConfig);

  useEffect(() => {
    // Prevent StrictMode double-mount from creating duplicate connections
    if (mountedRef.current) return;
    mountedRef.current = true;

    function handleBridgeEvent(event: string, payload: any) {
      switch (event) {
        case "message_create": {
          const author = payload.author || {};
          addBridgeMessage({
            type: "incoming",
            channel_id: payload.channel_id || "",
            guild_id: payload.guild_id,
            message_id: payload.id || "",
            author: { name: author.username || author.global_name || "Unknown", id: author.id || "" },
            content: payload.content || "",
            timestamp: payload.timestamp || new Date().toISOString(),
            routing_status: payload.routing_status,
            routing_detail: payload.routing_detail,
          });
          break;
        }
        case "ai_response": {
          addBridgeMessage({
            type: "outgoing",
            channel_id: payload.channel_id || "",
            guild_id: payload.guild_id,
            message_id: payload.message_id || "",
            author: { name: "AI", id: "ai" },
            content: payload.content || "",
            timestamp: payload.timestamp || new Date().toISOString(),
          });
          break;
        }
        case "voice_state_update": {
          setBridgeVoiceState(payload);
          break;
        }
        case "config_updated": {
          setBridgeDiscordConfig(payload);
          break;
        }
      }
    }

    function connect() {
      if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
        return;
      }

      const configuredOrigin = import.meta.env.VITE_BACKEND_WS_URL?.replace(/\/$/, "");
      // In Vite development, connect directly to FastAPI instead of routing a
      // long-lived socket through Vite's HTTP proxy. This avoids noisy
      // ECONNABORTED proxy messages when the backend is restarted and lets the
      // existing reconnect loop recover cleanly. Production keeps same-origin
      // routing so hosted deployments do not need a fixed port.
      const url = configuredOrigin
        ? `${configuredOrigin}/api/ws/bridge-events`
        : backendWebSocketUrl("/api/ws/bridge-events");

      try {
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
          console.log("[Bridge] Connected to bridge events");
          setBridgeConnected(true);
        };

        ws.onmessage = (e) => {
          try {
            const msg = JSON.parse(e.data);
            if (msg.type === "bridge_event") {
              handleBridgeEvent(msg.event, msg.payload);
            }
          } catch {
            // ignore malformed messages
          }
        };

        ws.onclose = () => {
          setBridgeConnected(false);
          wsRef.current = null;
          // Only reconnect if still mounted
          if (mountedRef.current) {
            reconnectTimer.current = setTimeout(connect, 3000);
          }
        };

        ws.onerror = () => {
          ws.close();
        };
      } catch {
        if (mountedRef.current) {
          reconnectTimer.current = setTimeout(connect, 3000);
        }
      }
    }

    // Ping interval to keep alive
    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, 30000);

    connect();

    return () => {
      mountedRef.current = false;
      clearInterval(pingInterval);
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent reconnect on intentional close
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [addBridgeMessage, setBridgeVoiceState, setBridgeConnected, setBridgeDiscordConfig]);
}
