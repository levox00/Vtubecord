# Personality System

## Representation

Personality traits are both descriptive and numeric (0.0 – 1.0).

Example traits:
- playfulness
- curiosity
- competitiveness
- confidence
- patience
- sarcasm
- friendliness
- risk_taking
- empathy
- stubbornness

Core identity (name, backstory, core values, immutable traits) is separate and much harder to change.

## Evolution Pipeline

Personality does **not** change on every conversation.

```
Experiences accumulate
    ↓
After N experiences or scheduled reflection
    ↓
Reflection agent analyzes patterns
    ↓
Produces CandidatePersonalityUpdate
    {
      trait: "competitiveness",
      old_value: 0.55,
      proposed_value: 0.61,
      reason: "Repeatedly requested rematches after losses and celebrated strategy improvements",
      evidence: [experience_ids...]
    }
    ↓
System or user can accept / reject / modify
    ↓
Accepted → write PersonalityChange record + update current trait
```

All changes are historical and auditable.  
Never silently overwrite.

## Influence on Behavior

Current personality values are injected into the prompt builder and can also affect:
- Response style
- Willingness to take risks / play games
- Proactive behavior frequency
- Emotional reaction magnitudes

## Relationship to Emotion

Emotion is short-term state (happiness, frustration, etc.).  
Personality is long-term disposition.  
Both influence the final prompt and avatar.