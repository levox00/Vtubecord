/**
 * UI Sound Effects — synthesized via Web Audio API (CC0, no external files).
 *
 * Classic Discord / app-style sounds for clicks, success, error, notifications, etc.
 * All sounds are generated at runtime — zero copyright, zero bundle bloat.
 */

let ctx: AudioContext | null = null;

function getCtx(): AudioContext {
  if (!ctx || ctx.state === "closed") {
    ctx = new AudioContext();
  }
  if (ctx.state === "suspended") {
    ctx.resume();
  }
  return ctx;
}

// --- Sound Effects ---

/** Soft click — button press, channel select */
export function sfxClick() {
  const c = getCtx();
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = "sine";
  o.frequency.setValueAtTime(1800, c.currentTime);
  o.frequency.exponentialRampToValueAtTime(900, c.currentTime + 0.06);
  g.gain.setValueAtTime(0.15, c.currentTime);
  g.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.08);
  o.connect(g);
  g.connect(c.destination);
  o.start(c.currentTime);
  o.stop(c.currentTime + 0.08);
}

/** Double-click / confirm — slightly deeper */
export function sfxConfirm() {
  const c = getCtx();
  // First click
  const o1 = c.createOscillator();
  const g1 = c.createGain();
  o1.type = "sine";
  o1.frequency.setValueAtTime(1600, c.currentTime);
  o1.frequency.exponentialRampToValueAtTime(800, c.currentTime + 0.05);
  g1.gain.setValueAtTime(0.12, c.currentTime);
  g1.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.06);
  o1.connect(g1);
  g1.connect(c.destination);
  o1.start(c.currentTime);
  o1.stop(c.currentTime + 0.06);
  // Second click (delayed)
  const o2 = c.createOscillator();
  const g2 = c.createGain();
  o2.type = "sine";
  o2.frequency.setValueAtTime(2000, c.currentTime + 0.08);
  o2.frequency.exponentialRampToValueAtTime(1200, c.currentTime + 0.14);
  g2.gain.setValueAtTime(0, c.currentTime);
  g2.gain.setValueAtTime(0.12, c.currentTime + 0.08);
  g2.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.16);
  o2.connect(g2);
  g2.connect(c.destination);
  o2.start(c.currentTime + 0.08);
  o2.stop(c.currentTime + 0.16);
}

/** Success — ascending two-note chime */
export function sfxSuccess() {
  const c = getCtx();
  // Note 1
  const o1 = c.createOscillator();
  const g1 = c.createGain();
  o1.type = "sine";
  o1.frequency.value = 523; // C5
  g1.gain.setValueAtTime(0.15, c.currentTime);
  g1.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.3);
  o1.connect(g1);
  g1.connect(c.destination);
  o1.start(c.currentTime);
  o1.stop(c.currentTime + 0.3);
  // Note 2 (higher)
  const o2 = c.createOscillator();
  const g2 = c.createGain();
  o2.type = "sine";
  o2.frequency.value = 659; // E5
  g2.gain.setValueAtTime(0, c.currentTime);
  g2.gain.setValueAtTime(0.15, c.currentTime + 0.12);
  g2.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.45);
  o2.connect(g2);
  g2.connect(c.destination);
  o2.start(c.currentTime + 0.12);
  o2.stop(c.currentTime + 0.45);
}

/** Error — descending two-tone buzz */
export function sfxError() {
  const c = getCtx();
  // Note 1 (high)
  const o1 = c.createOscillator();
  const g1 = c.createGain();
  o1.type = "square";
  o1.frequency.value = 330;
  g1.gain.setValueAtTime(0.08, c.currentTime);
  g1.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.15);
  o1.connect(g1);
  g1.connect(c.destination);
  o1.start(c.currentTime);
  o1.stop(c.currentTime + 0.15);
  // Note 2 (low)
  const o2 = c.createOscillator();
  const g2 = c.createGain();
  o2.type = "square";
  o2.frequency.value = 220;
  g2.gain.setValueAtTime(0, c.currentTime);
  g2.gain.setValueAtTime(0.08, c.currentTime + 0.12);
  g2.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.35);
  o2.connect(g2);
  g2.connect(c.destination);
  o2.start(c.currentTime + 0.12);
  o2.stop(c.currentTime + 0.35);
}

/** Critical error — harsh descending buzz */
export function sfxCritical() {
  const c = getCtx();
  const o1 = c.createOscillator();
  const g1 = c.createGain();
  o1.type = "sawtooth";
  o1.frequency.setValueAtTime(400, c.currentTime);
  o1.frequency.linearRampToValueAtTime(150, c.currentTime + 0.4);
  g1.gain.setValueAtTime(0.1, c.currentTime);
  g1.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.45);
  o1.connect(g1);
  g1.connect(c.destination);
  o1.start(c.currentTime);
  o1.stop(c.currentTime + 0.45);
  // Second layer for thickness
  const o2 = c.createOscillator();
  const g2 = c.createGain();
  o2.type = "square";
  o2.frequency.setValueAtTime(350, c.currentTime);
  o2.frequency.linearRampToValueAtTime(130, c.currentTime + 0.4);
  g2.gain.setValueAtTime(0.06, c.currentTime);
  g2.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.45);
  o2.connect(g2);
  g2.connect(c.destination);
  o2.start(c.currentTime);
  o2.stop(c.currentTime + 0.45);
}

/** Notification — gentle ding */
export function sfxNotification() {
  const c = getCtx();
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = "sine";
  o.frequency.value = 880; // A5
  g.gain.setValueAtTime(0.12, c.currentTime);
  g.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.5);
  o.connect(g);
  g.connect(c.destination);
  o.start(c.currentTime);
  o.stop(c.currentTime + 0.5);
}

/** Message received — soft two-note pop */
export function sfxMessage() {
  const c = getCtx();
  const o1 = c.createOscillator();
  const g1 = c.createGain();
  o1.type = "sine";
  o1.frequency.value = 600;
  g1.gain.setValueAtTime(0.1, c.currentTime);
  g1.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.12);
  o1.connect(g1);
  g1.connect(c.destination);
  o1.start(c.currentTime);
  o1.stop(c.currentTime + 0.12);
  const o2 = c.createOscillator();
  const g2 = c.createGain();
  o2.type = "sine";
  o2.frequency.value = 900;
  g2.gain.setValueAtTime(0, c.currentTime);
  g2.gain.setValueAtTime(0.1, c.currentTime + 0.08);
  g2.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.25);
  o2.connect(g2);
  g2.connect(c.destination);
  o2.start(c.currentTime + 0.08);
  o2.stop(c.currentTime + 0.25);
}

/** Voice connected — ascending sweep */
export function sfxConnect() {
  const c = getCtx();
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = "sine";
  o.frequency.setValueAtTime(300, c.currentTime);
  o.frequency.exponentialRampToValueAtTime(800, c.currentTime + 0.2);
  o.frequency.exponentialRampToValueAtTime(1200, c.currentTime + 0.35);
  g.gain.setValueAtTime(0.1, c.currentTime);
  g.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.4);
  o.connect(g);
  g.connect(c.destination);
  o.start(c.currentTime);
  o.stop(c.currentTime + 0.4);
}

/** Voice disconnected — descending sweep */
export function sfxDisconnect() {
  const c = getCtx();
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = "sine";
  o.frequency.setValueAtTime(800, c.currentTime);
  o.frequency.exponentialRampToValueAtTime(300, c.currentTime + 0.25);
  g.gain.setValueAtTime(0.1, c.currentTime);
  g.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.3);
  o.connect(g);
  g.connect(c.destination);
  o.start(c.currentTime);
  o.stop(c.currentTime + 0.3);
}

/** Toggle on — short ascending blip */
export function sfxToggleOn() {
  const c = getCtx();
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = "sine";
  o.frequency.setValueAtTime(600, c.currentTime);
  o.frequency.exponentialRampToValueAtTime(1000, c.currentTime + 0.08);
  g.gain.setValueAtTime(0.1, c.currentTime);
  g.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.12);
  o.connect(g);
  g.connect(c.destination);
  o.start(c.currentTime);
  o.stop(c.currentTime + 0.12);
}

/** Toggle off — short descending blip */
export function sfxToggleOff() {
  const c = getCtx();
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = "sine";
  o.frequency.setValueAtTime(1000, c.currentTime);
  o.frequency.exponentialRampToValueAtTime(600, c.currentTime + 0.08);
  g.gain.setValueAtTime(0.1, c.currentTime);
  g.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.12);
  o.connect(g);
  g.connect(c.destination);
  o.start(c.currentTime);
  o.stop(c.currentTime + 0.12);
}

/** Whoosh — transition between views */
export function sfxWhoosh() {
  const c = getCtx();
  const bufferSize = c.sampleRate * 0.25;
  const buffer = c.createBuffer(1, bufferSize, c.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < bufferSize; i++) {
    data[i] = (Math.random() * 2 - 1) * (1 - i / bufferSize);
  }
  const noise = c.createBufferSource();
  noise.buffer = buffer;
  const bandpass = c.createBiquadFilter();
  bandpass.type = "bandpass";
  bandpass.frequency.setValueAtTime(500, c.currentTime);
  bandpass.frequency.exponentialRampToValueAtTime(2000, c.currentTime + 0.12);
  bandpass.frequency.exponentialRampToValueAtTime(400, c.currentTime + 0.25);
  bandpass.Q.value = 2;
  const g = c.createGain();
  g.gain.setValueAtTime(0.08, c.currentTime);
  g.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.25);
  noise.connect(bandpass);
  bandpass.connect(g);
  g.connect(c.destination);
  noise.start(c.currentTime);
  noise.stop(c.currentTime + 0.25);
}

// --- Master volume control ---

let masterVolume = 0.7;

/** Set master volume (0.0 – 1.0) */
export function setSfxVolume(v: number) {
  masterVolume = Math.max(0, Math.min(1, v));
}

/** Get current master volume */
export function getSfxVolume(): number {
  return masterVolume;
}
