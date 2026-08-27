# Hosted Models

The application treats every LLM provider through the same `LLMProvider` interface.

## Supported (Phase 1+)

| Provider              | Config key          | Notes                          |
|-----------------------|---------------------|--------------------------------|
| OpenAI-compatible     | `openai_compatible` | Works with OpenAI, Groq, Together, Fireworks, local servers, etc. |
| Anthropic             | `anthropic`         | Claude models                  |
| Google Gemini         | `gemini`            |                                |
| Ollama                | `ollama`            | Local or remote Ollama         |

## Configuration Example

```yaml
llm:
  provider: openai_compatible
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o-mini"
  api_key_env: "OPENAI_API_KEY"   # read from environment
  temperature: 0.8
  max_tokens: 1024
```

API keys are **never** stored in the database.  
Use environment variables or the OS credential store.

## Switching Providers

1. Change the `llm` section in `config.yaml` **or**
2. Use the Model Manager UI (later phases)

The character remains the same because all durable state lives in the database.

## Testing Model Independence

A good test:

1. Have 50–100 conversations with Character A using local model
2. Switch to a hosted model
3. Verify memories, personality traits, relationships, and goals are still present and influence behavior

If the character “forgets” or changes personality, that is a bug in the prompt builder or state loading — not expected behavior.