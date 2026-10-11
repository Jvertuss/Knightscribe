import { useEffect, useRef, useState } from "react";

// The Pi streams raw sound at /audio while recording: 16 kHz, mono, 16-bit.
const RATE = 16000;
const START_DELAY = 0.3; // seconds of sound kept ready, so small network hiccups don't cut out
const MAX_DELAY = 1.0; // if we fall further behind the video than this, skip ahead

type State = "off" | "waiting" | "playing" | "error";

interface LiveAudioBarProps {
  src: string; // e.g. http://knightcribe.local:5000/audio
}

// Listen / mute button, volume slider and level meter for the live lecture sound
function LiveAudioBar({ src }: LiveAudioBarProps) {
  const [on, setOn] = useState(false);
  const [state, setState] = useState<State>("off");
  const [volume, setVolume] = useState(0.8);
  const [level, setLevel] = useState(0);
  const gainRef = useRef<GainNode | null>(null);
  const volumeRef = useRef(volume);

  useEffect(() => {
    volumeRef.current = volume;
    if (gainRef.current) gainRef.current.gain.value = volume;
  }, [volume]);

  useEffect(() => {
    if (!on) return;
    // created after the click, so the browser allows it to make sound
    const ctx = new AudioContext();
    const gain = ctx.createGain();
    gain.gain.value = volumeRef.current;
    gain.connect(ctx.destination);
    gainRef.current = gain;

    const controller = new AbortController();
    let playAt = 0;
    let leftover: Uint8Array | null = null; // half a sample left over from the last piece

    async function listen() {
      try {
        const res = await fetch(src, { signal: controller.signal, cache: "no-store" });
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
        const reader = res.body.getReader();

        for (;;) {
          const { value, done } = await reader.read();
          if (done) throw new Error("the sound stream ended");

          let bytes = value;
          if (leftover) {
            const joined = new Uint8Array(leftover.length + bytes.length);
            joined.set(leftover);
            joined.set(bytes, leftover.length);
            bytes = joined;
          }
          const usable = bytes.length - (bytes.length % 2);
          leftover = usable < bytes.length ? bytes.slice(usable) : null;
          if (usable === 0) continue;

          const samples = new Int16Array(bytes.slice(0, usable).buffer);
          const buffer = ctx.createBuffer(1, samples.length, RATE);
          const channel = buffer.getChannelData(0);
          let peak = 0;
          for (let i = 0; i < samples.length; i++) {
            channel[i] = samples[i] / 32768;
            peak = Math.max(peak, Math.abs(channel[i]));
          }
          setLevel(peak);
          setState("playing");

          const now = ctx.currentTime;
          if (playAt < now) playAt = now + START_DELAY; // first piece, or we ran dry
          if (playAt > now + MAX_DELAY) continue; // too far behind the video: drop this piece
          const source = ctx.createBufferSource();
          source.buffer = buffer;
          source.connect(gain);
          source.start(playAt);
          playAt += buffer.duration;
        }
      } catch {
        if (controller.signal.aborted) return; // the student pressed Mute
        setState("error");
        setLevel(0);
        setOn(false);
      }
    }
    listen();

    return () => {
      controller.abort();
      gainRef.current = null;
      ctx.close();
    };
  }, [on, src]);

  function toggle() {
    if (on) {
      setOn(false);
      setState("off");
      setLevel(0);
    } else {
      setOn(true);
      setState("waiting");
    }
  }

  const label = {
    off: "Sound is off",
    waiting: "Waiting for sound... (only while the lecture is recording)",
    playing: "Live sound",
    error: "Can't reach the classroom sound. Press Listen to try again.",
  }[state];

  return (
    <div className="audio-bar">
      <button
        className={on ? "audio-toggle on" : "audio-toggle"}
        onClick={toggle}
        aria-pressed={on}
      >
        {on ? "Mute" : "Listen"}
      </button>

      <div className="audio-info">
        <span className={state === "error" ? "audio-label error" : "audio-label"}>
          {label}
        </span>
        <span className="audio-meter" aria-hidden="true">
          <span style={{ width: `${Math.min(100, Math.round(level * 140))}%` }} />
        </span>
      </div>

      <input
        className="audio-volume"
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={volume}
        onChange={(e) => setVolume(Number(e.target.value))}
        aria-label="Volume"
      />
    </div>
  );
}

export default LiveAudioBar;
