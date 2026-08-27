# Tool Calling mit lokalen LLMs – Struktur & Anleitung
### Praxisbeispiel: Spotify Web API

Diese Anleitung zeigt dir, wie du **Tool Calling (Function Calling)** mit einem **lokal laufenden, tool-calling-fähigen Instruct-Modell** umsetzt und daran anbindest – am konkreten Beispiel einer **Spotify Developer App**.

---

## 1. Was ist Tool Calling?

Tool Calling bedeutet, dass du dem Sprachmodell eine Liste verfügbarer Funktionen ("Tools") inklusive Beschreibung und Parameter-Schema mitgibst. Das Modell entscheidet dann selbst:

- Kann ich die Anfrage direkt beantworten? → normale Textantwort
- Brauche ich Daten oder eine Aktion von außen? → es antwortet **nicht** mit Text, sondern mit einem strukturierten `tool_calls`-Objekt (Funktionsname + JSON-Argumente)

Dein Code führt die Funktion aus, gibt das Ergebnis zurück ans Modell, und das Modell formuliert daraus die finale Antwort. Das Modell selbst führt **nie** Code aus – es "entscheidet und beschreibt", dein Programm "handelt".

---

## 2. Architektur im Überblick

```
┌─────────────┐        1. Prompt + Tool-Definitionen        ┌──────────────┐
│   Dein Code  │ ───────────────────────────────────────────▶ │ Lokales LLM  │
│  (Python)    │                                              │ (Ollama/     │
│              │ ◀─────────────────────────────────────────── │  llama.cpp/  │
│              │   2. Antwort: Text  ODER  tool_calls[]        │  vLLM/LM     │
│              │                                              │  Studio)     │
│  3. Tool     │                                              └──────────────┘
│  ausführen   │
│  (z.B.       │
│  Spotify-API)│
│              │
│  4. Ergebnis │
│  als role=   │
│  "tool"      │──────────────────────────────────────────────▶  (zurück ans Modell,
│  zurückgeben │                                                  Schritt 2 wiederholt sich,
└─────────────┘                                                  bis keine tool_calls mehr kommen)
```

Der gesamte Ablauf ist eine **Schleife**: Anfrage → Modell → (Tool-Aufruf → Ergebnis) × n → finale Textantwort.

---

## 3. Voraussetzungen

### 3.1 Ein tool-calling-fähiges lokales Modell

Nicht jedes Instruct-Modell unterstützt strukturiertes Tool Calling zuverlässig. Gut geeignet sind aktuell u. a.:

- **Llama 3.1 / 3.2 / 3.3** (Meta)
- **Qwen 2.5 / Qwen 3** Instruct-Varianten
- **Mistral Nemo / Mistral Small** Instruct
- **Hermes 3** (NousResearch)
- **gpt-oss-20b / gpt-oss-120b** (OpenAI, offen)
- **DeepSeek-V2.5+**

### 3.2 Ein Inference-Server mit OpenAI-kompatiblem `tools`-Parameter

Du brauchst einen lokalen Server, der Requests im OpenAI-`/v1/chat/completions`-Format inklusive `tools` und `tool_calls` entgegennimmt. Die gängigsten Optionen:

| Server | Endpoint | Hinweis |
|---|---|---|
| **Ollama** | `http://localhost:11434/v1` | Tool Calling nativ unterstützt für kompatible Modelle |
| **llama.cpp server** | `http://localhost:8081/v1` | Mit `--jinja` starten, damit das Chat-Template inkl. Tool-Support geladen wird; 8081 vermeidet den häufigen CEF/Discord-Konflikt auf 8080 |
| **vLLM** | `http://localhost:8000/v1` | Mit `--enable-auto-tool-choice --tool-call-parser <parser>` starten |
| **LM Studio** | `http://localhost:1234/v1` | GUI-basiert, Tool Calling im Server-Modus |

Alle vier sprechen **dasselbe Nachrichtenformat**, dein Python-Code bleibt also nahezu identisch – du tauschst nur `base_url` und Modellnamen.

### 3.3 Python-Pakete

```bash
pip install openai spotipy python-dotenv
```

- `openai` – wird als generischer Client für **jeden** OpenAI-kompatiblen Server genutzt (auch lokal, kein OpenAI-Account nötig)
- `spotipy` – schlanker Python-Wrapper für die Spotify Web API
- `python-dotenv` – zum Laden von Zugangsdaten aus einer `.env`-Datei

---

## 4. Grundstruktur des Tool-Calling-Workflows

Der generische Ablauf, unabhängig vom konkreten Tool:

1. **Tools definieren** – JSON-Schema pro Funktion (Name, Beschreibung, Parameter)
2. **Anfrage senden** – User-Message + `tools`-Liste ans Modell
3. **Antwort prüfen** – enthält sie `tool_calls`?
4. **Falls ja:** Tool lokal ausführen, Ergebnis als Message mit `role: "tool"` zurückgeben, zurück zu Schritt 2
5. **Falls nein:** Modell hat eine finale Textantwort geliefert → fertig

### Generisches Code-Skelett

```python
from openai import OpenAI
import json

# base_url zeigt auf deinen lokalen Server, api_key ist Pflichtfeld,
# wird lokal aber ignoriert
client = OpenAI(base_url="http://localhost:11434/v1", api_key="lokal")

MODEL = "llama3.1"  # exakter Modellname, z.B. via `ollama list`

def run_conversation(user_input: str, tools: list, tool_functions: dict):
    messages = [{"role": "user", "content": user_input}]

    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            # Modell hat fertig geantwortet
            return msg.content

        # Modell will ein oder mehrere Tools aufrufen
        for call in msg.tool_calls:
            fn_name = call.function.name
            fn_args = json.loads(call.function.arguments)

            if fn_name in tool_functions:
                try:
                    result = tool_functions[fn_name](**fn_args)
                except Exception as e:
                    result = {"error": str(e)}
            else:
                result = {"error": f"Unbekanntes Tool: {fn_name}"}

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
```

Dieses Skelett ist bewusst generisch – die Spotify-Tools klinken sich unten nur als `tools`-Liste und `tool_functions`-Dictionary ein.

---

## 5. Spotify Developer Setup

### 5.1 Wichtiger aktueller Hinweis (Stand 2026)

Spotify hat seine **Developer-Mode-Regeln im Februar/März 2026 verschärft**: Für neue Apps im Development Mode ist inzwischen ein **aktives Premium-Abo** des App-Besitzers erforderlich, es ist nur noch **eine Development-Mode-App pro Entwickler** erlaubt, und jede App darf nur noch **bis zu 5 autorisierte Nutzer** haben. Zusätzlich wurden einige Endpunkte (z. B. Bulk-Metadaten, manche Artist-Endpunkte) im Development Mode eingeschränkt. Für ein persönliches Projekt wie dieses reicht das völlig aus – du solltest es nur einplanen.

### 5.2 App im Dashboard anlegen

1. Gehe zu **https://developer.spotify.com/dashboard** und logge dich mit deinem Spotify-Account ein (Premium empfohlen/erforderlich)
2. **Create app** klicken
3. App-Name und Beschreibung eintragen
4. **Redirect URI** eintragen, z. B. `http://127.0.0.1:8888/callback` (muss exakt mit dem später im Code verwendeten Wert übereinstimmen, kein abschließender Slash)
5. Nutzungsbedingungen akzeptieren, App erstellen
6. Im App-Dashboard findest du **Client ID** und (hinter "View client secret") das **Client Secret**

### 5.3 Zwei Auth-Flows – wann welchen?

| Flow | Zugriff auf Nutzerdaten/Playback? | Für dieses Tool-Calling-Beispiel |
|---|---|---|
| **Client Credentials Flow** | Nein – nur öffentliche Katalogdaten (z. B. Suche) | Reicht für `search_track` |
| **Authorization Code Flow** | Ja – z. B. Wiedergabe steuern, aktueller Track | Nötig für `play_track`, `pause`, `skip` etc. |

Da unser Beispiel Musik **abspielen/steuern** soll, brauchen wir den **Authorization Code Flow** mit den passenden **Scopes**:

- `user-read-playback-state` – aktuellen Player-Status lesen
- `user-modify-playback-state` – Wiedergabe steuern (Play/Pause/Skip/Volume)
- `user-read-currently-playing` – aktuell laufenden Track lesen

### 5.4 `.env`-Datei anlegen

```env
SPOTIPY_CLIENT_ID=deine_client_id
SPOTIPY_CLIENT_SECRET=dein_client_secret
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

`spotipy` liest diese Umgebungsvariablen automatisch, wenn du `python-dotenv` beim Start lädst.

---

## 6. Spotify-Wrapper mit `spotipy`

```python
import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    scope=SCOPES,
    cache_path=".spotify_cache",  # speichert Access/Refresh-Token lokal zwischen
    open_browser=True,            # öffnet beim ersten Mal den Login-Browser
))
```

Beim allerersten Aufruf öffnet sich ein Browserfenster mit dem Spotify-Login und der Berechtigungsabfrage. Danach kümmert sich `spotipy` automatisch um das Erneuern des Access Tokens via Refresh Token – du musst dich nicht erneut einloggen, solange der Cache besteht.

---

## 7. Die eigentlichen Tool-Funktionen

Diese Python-Funktionen sind die tatsächliche Logik, die vom Modell "getriggert" wird:

```python
def search_track(query: str, limit: int = 5) -> dict:
    """Sucht Songs auf Spotify nach Titel/Künstler."""
    results = sp.search(q=query, type="track", limit=limit)
    tracks = results["tracks"]["items"]
    return {
        "results": [
            {
                "name": t["name"],
                "artist": t["artists"][0]["name"],
                "uri": t["uri"],
                "album": t["album"]["name"],
            }
            for t in tracks
        ]
    }

def play_track(track_uri: str) -> dict:
    """Spielt einen konkreten Track auf dem aktiven Gerät ab."""
    devices = sp.devices()["devices"]
    if not devices:
        return {"error": "Kein aktives Spotify-Gerät gefunden. Bitte Spotify auf einem Gerät öffnen."}
    sp.start_playback(uris=[track_uri])
    return {"status": "playing", "uri": track_uri}

def pause_playback() -> dict:
    """Pausiert die aktuelle Wiedergabe."""
    sp.pause_playback()
    return {"status": "paused"}

def skip_next() -> dict:
    """Springt zum nächsten Track."""
    sp.next_track()
    return {"status": "skipped"}

def get_currently_playing() -> dict:
    """Gibt den aktuell laufenden Track zurück."""
    current = sp.current_playback()
    if not current or not current.get("item"):
        return {"status": "nothing_playing"}
    item = current["item"]
    return {
        "track": item["name"],
        "artist": item["artists"][0]["name"],
        "is_playing": current["is_playing"],
    }

def set_volume(percent: int) -> dict:
    """Setzt die Lautstärke (0-100)."""
    sp.volume(percent)
    return {"status": "volume_set", "percent": percent}
```

---

## 8. Tool-Definitionen (JSON Schema) für das Modell

Das Modell "sieht" nur diese Beschreibung – nicht deinen Python-Code. Präzise Beschreibungen sind entscheidend dafür, dass das Modell die richtige Funktion zur richtigen Zeit aufruft.

```python
spotify_tools = [
    {
        "type": "function",
        "function": {
            "name": "search_track",
            "description": "Sucht Songs auf Spotify anhand eines Suchbegriffs (Titel und/oder Künstler).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchbegriff, z.B. 'Currents Tame Impala'",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximale Anzahl Ergebnisse",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_track",
            "description": "Startet die Wiedergabe eines konkreten Songs anhand seiner Spotify-URI. Erfordert vorher eine Suche mit search_track, um die URI zu erhalten.",
            "parameters": {
                "type": "object",
                "properties": {
                    "track_uri": {
                        "type": "string",
                        "description": "Spotify-URI des Tracks, z.B. 'spotify:track:xxxxxxxxxxxx'",
                    },
                },
                "required": ["track_uri"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pause_playback",
            "description": "Pausiert die aktuell laufende Spotify-Wiedergabe.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skip_next",
            "description": "Überspringt den aktuellen Song und spielt den nächsten Titel ab.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_currently_playing",
            "description": "Gibt zurück, welcher Song gerade auf Spotify läuft.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Stellt die Lautstärke der Spotify-Wiedergabe ein.",
            "parameters": {
                "type": "object",
                "properties": {
                    "percent": {
                        "type": "integer",
                        "description": "Lautstärke in Prozent, 0 bis 100",
                    },
                },
                "required": ["percent"],
            },
        },
    },
]

tool_functions = {
    "search_track": search_track,
    "play_track": play_track,
    "pause_playback": pause_playback,
    "skip_next": skip_next,
    "get_currently_playing": get_currently_playing,
    "set_volume": set_volume,
}
```

---

## 9. Alles zusammen: kompletter Chat-Loop

```python
import os
import json
from dotenv import load_dotenv
from openai import OpenAI
import spotipy
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

# --- Lokales LLM ---
client = OpenAI(base_url="http://localhost:11434/v1", api_key="lokal")
MODEL = "llama3.1"

# --- Spotify ---
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(scope=SCOPES, cache_path=".spotify_cache"))

# --- Tool-Funktionen & Definitionen wie oben ---
# (search_track, play_track, pause_playback, skip_next,
#  get_currently_playing, set_volume, spotify_tools, tool_functions)

SYSTEM_PROMPT = (
    "Du bist ein hilfreicher Assistent mit Zugriff auf Spotify. "
    "Nutze die verfügbaren Tools, um Songs zu suchen und die Wiedergabe zu steuern. "
    "Frage bei Mehrdeutigkeit kurz nach, statt zu raten."
)

def run_conversation(user_input: str, history: list | None = None) -> tuple[str, list]:
    messages = history or [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "user", "content": user_input})

    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=spotify_tools,
            tool_choice="auto",
        )
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return msg.content, messages

        for call in msg.tool_calls:
            fn_name = call.function.name
            fn_args = json.loads(call.function.arguments or "{}")
            fn = tool_functions.get(fn_name)

            if fn is None:
                result = {"error": f"Unbekanntes Tool: {fn_name}"}
            else:
                try:
                    result = fn(**fn_args)
                except Exception as e:
                    result = {"error": str(e)}

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })


if __name__ == "__main__":
    conversation = None
    print("Spotify-Assistent bereit. Tippe 'exit' zum Beenden.")
    while True:
        user_text = input("\nDu: ")
        if user_text.strip().lower() == "exit":
            break
        answer, conversation = run_conversation(user_text, conversation)
        print(f"Assistent: {answer}")
```

---

## 10. Beispiel-Interaktion

```
Du: Spiel mal was von Tame Impala
```

Ablauf im Hintergrund:

1. Modell ruft `search_track(query="Tame Impala")` auf
2. Tool liefert eine Liste von Treffern mit URIs zurück
3. Modell ruft `play_track(track_uri="spotify:track:...")` mit der ersten passenden URI auf
4. Tool startet Wiedergabe, gibt Status zurück
5. Modell antwortet: *"Ich spiele jetzt 'The Less I Know The Better' von Tame Impala."*

```
Du: Was läuft gerade?
```

1. Modell ruft `get_currently_playing()` auf
2. Modell antwortet mit Titel/Künstler aus dem Tool-Ergebnis

---

## 11. Best Practices

- **Präzise Tool-Beschreibungen** – das Modell entscheidet allein anhand von `description` und Parameter-Namen, welches Tool passt. Vage Beschreibungen führen zu Fehlaufrufen.
- **Strikte JSON-Schemas** – definiere `required`, sinnvolle `type`s und wo möglich `enum`-Werte, um Fehleingaben des Modells zu minimieren.
- **Fehler nie crashen lassen** – Exceptions im Tool abfangen und als `{"error": "..."}` zurückgeben. Das Modell kann damit umgehen und dem Nutzer eine sinnvolle Antwort geben.
- **Kein Blind-Vertrauen bei kritischen Aktionen** – bei potenziell "gefährlichen" Tools (z. B. Playlist löschen) kannst du im System-Prompt oder in deinem Code eine Bestätigungsschleife einbauen, bevor das Tool wirklich ausgeführt wird.
- **Rate Limits beachten** – die Spotify-API liefert bei Überschreitung `429` mit `Retry-After`-Header; `spotipy` wirft dann eine Exception, die du im Tool abfangen solltest.
- **Token-Handling nicht selbst bauen** – `spotipy`'s `cache_path` übernimmt Refresh-Token-Handling automatisch, das spart viel Fehleranfälligkeit.
- **Modell-spezifische Templates** – Server wie Ollama oder llama.cpp normalisieren das Tool-Call-Format weitgehend auf den OpenAI-Standard, trotzdem lohnt sich ein Blick in die Doku deines konkreten Modells, falls Tool Calls nicht sauber erkannt werden.
- **Parallele Tool Calls** – manche Modelle geben mehrere `tool_calls` in einer Antwort zurück; die `for call in msg.tool_calls`-Schleife im Beispiel deckt das bereits ab.

---

## 12. Muster zur Erweiterung um weitere Tools

Um ein neues Tool hinzuzufügen, brauchst du immer nur drei Schritte:

1. **Python-Funktion schreiben**, die das eigentliche Tun übernimmt und ein JSON-serialisierbares Ergebnis zurückgibt
2. **JSON-Schema-Eintrag** in die `tools`-Liste ergänzen (Name, Beschreibung, Parameter)
3. **Funktion im `tool_functions`-Dictionary registrieren**

Dieses Muster funktioniert identisch für jede andere API – ob Kalender, Smart-Home, Datenbank oder ein anderer Musikdienst.

---

## 13. Weiterführende Links

- Spotify Web API Doku: https://developer.spotify.com/documentation/web-api
- Spotify Scopes-Referenz: https://developer.spotify.com/documentation/web-api/concepts/scopes
- Spotify Authorization Code Flow: https://developer.spotify.com/documentation/web-api/tutorials/code-flow
- Migration Guide zu den Februar-2026-Änderungen: https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide
- spotipy Doku: https://spotipy.readthedocs.io
- Ollama Tool Support: https://ollama.com/blog/tool-support
- Ollama OpenAI-Kompatibilität: https://docs.ollama.com/api/openai-compatibility
