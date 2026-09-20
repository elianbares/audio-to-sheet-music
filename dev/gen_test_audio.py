"""
Dev-only helper: generates synthetic WAV files with KNOWN ground-truth notes
and rhythms, so we can test the transcription pipeline against an answer key
instead of guessing whether output "looks right".

Not part of the shipped app. Run with:
    source venv/bin/activate
    python dev/gen_test_audio.py
"""
import os
import numpy as np
import soundfile as sf

SR = 22050
OUT_DIR = os.path.join(os.path.dirname(__file__), "test_audio")
os.makedirs(OUT_DIR, exist_ok=True)


def midi_to_freq(midi):
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


NOTE_NAMES = {
    "C4": 60, "D4": 62, "E4": 64, "F4": 65, "G4": 67, "A4": 69, "B4": 71, "C5": 72,
    "D5": 74, "E5": 76,
}


def synth_note(freq, duration, sr=SR, kind="piano", vibrato=False, amp=0.3):
    """Additive synth with a percussive (piano-like) or sustained (voice-like)
    envelope, a few harmonics, and optional vibrato."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)

    if vibrato:
        vib_rate = 5.5  # Hz
        vib_depth = 0.008  # fraction of freq
        inst_freq = freq * (1 + vib_depth * np.sin(2 * np.pi * vib_rate * t))
        phase = 2 * np.pi * np.cumsum(inst_freq) / sr
    else:
        phase = 2 * np.pi * freq * t

    harmonics = [1.0, 0.5, 0.25, 0.12, 0.06]
    signal = np.zeros_like(t)
    for i, h_amp in enumerate(harmonics, start=1):
        signal += h_amp * np.sin(i * phase)
    signal /= sum(harmonics)

    if kind == "piano":
        # fast attack, exponential decay
        attack = int(0.005 * sr)
        env = np.ones_like(t)
        decay_rate = 2.2 / max(duration, 0.05)
        env = np.exp(-decay_rate * t)
        if attack > 0:
            env[:attack] *= np.linspace(0, 1, attack)
    else:  # sustained / voice-like
        attack = int(0.06 * sr)
        release = int(0.08 * sr)
        env = np.ones_like(t)
        if attack > 0:
            env[:attack] = np.linspace(0, 1, attack)
        if release > 0 and release < len(env):
            env[-release:] *= np.linspace(1, 0, release)

    return amp * signal * env


def silence(duration, sr=SR):
    return np.zeros(int(sr * duration))


def write(name, audio, sr=SR):
    path = os.path.join(OUT_DIR, name)
    audio = np.clip(audio, -1.0, 1.0).astype(np.float32)
    sf.write(path, audio, sr)
    print(f"wrote {path} ({len(audio)/sr:.2f}s)")


def concat(*parts):
    return np.concatenate(parts)


# ---- 1. single sustained note: A4, 2 seconds ----
write("01_single_note_A4.wav", synth_note(midi_to_freq(69), 2.0, kind="sustain"))

# ---- 2. C major scale, quarter notes at 100 BPM (0.6s each) ----
scale = ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5"]
qlen = 0.6
audio = concat(*[synth_note(midi_to_freq(NOTE_NAMES[n]), qlen, kind="piano") for n in scale])
write("02_c_major_scale.wav", audio)

# ---- 3. rhythms: quarter, eighth, sixteenth notes on C4, 120 BPM (quarter=0.5s) ----
q = 0.5
freq = midi_to_freq(NOTE_NAMES["C4"])
parts = []
# 4 quarters
for _ in range(4):
    parts.append(synth_note(freq, q, kind="piano"))
# 4 eighths (2 quarters worth)
for _ in range(4):
    parts.append(synth_note(freq, q / 2, kind="piano"))
# 8 sixteenths (2 quarters worth)
for _ in range(8):
    parts.append(synth_note(freq, q / 4, kind="piano"))
write("03_rhythms.wav", concat(*parts))

# ---- 4. rests: note, silence, note, silence (quarter=0.5s each slot) ----
parts = [
    synth_note(midi_to_freq(NOTE_NAMES["C4"]), 0.5, kind="piano"),
    silence(0.5),
    synth_note(midi_to_freq(NOTE_NAMES["E4"]), 0.5, kind="piano"),
    silence(0.5),
    synth_note(midi_to_freq(NOTE_NAMES["G4"]), 1.0, kind="piano"),
]
write("04_rests.wav", concat(*parts))

# ---- 5. sustained whole note, 4 seconds, G4 ----
write("05_sustained_note_G4.wav", synth_note(midi_to_freq(NOTE_NAMES["G4"]), 4.0, kind="sustain"))

# ---- 6. chords: C major triad, then F major triad, then G major triad (piano-like) ----
def chord(freqs, duration, kind="piano"):
    parts = [synth_note(f, duration, kind=kind, amp=0.2) for f in freqs]
    n = max(len(p) for p in parts)
    out = np.zeros(n)
    for p in parts:
        out[: len(p)] += p
    return out


c_maj = chord([midi_to_freq(60), midi_to_freq(64), midi_to_freq(67)], 1.2)
f_maj = chord([midi_to_freq(65), midi_to_freq(69), midi_to_freq(72)], 1.2)
g_maj = chord([midi_to_freq(67), midi_to_freq(71), midi_to_freq(74)], 1.2)
write("06_chords.wav", concat(c_maj, f_maj, g_maj))

# ---- 7. repeated notes: same pitch 8 times, quarter notes ----
freq = midi_to_freq(NOTE_NAMES["E4"])
audio = concat(*[synth_note(freq, 0.4, kind="piano") for _ in range(8)])
write("07_repeated_notes.wav", audio)

# ---- 8. tempo change: slow quarters then fast quarters, same pitches ----
slow = concat(*[synth_note(midi_to_freq(NOTE_NAMES[n]), 0.8, kind="piano") for n in ["C4", "D4", "E4", "F4"]])
fast = concat(*[synth_note(midi_to_freq(NOTE_NAMES[n]), 0.3, kind="piano") for n in ["C4", "D4", "E4", "F4"]])
write("08_tempo_change.wav", concat(slow, fast))

# ---- 9. simple melody resembling "Twinkle Twinkle Little Star" opening ----
# C C G G A A G(half) F F E E D D C(half)  -- quarter=0.5s, half=1.0s
mel = [
    ("C4", 0.5), ("C4", 0.5), ("G4", 0.5), ("G4", 0.5),
    ("A4", 0.5), ("A4", 0.5), ("G4", 1.0),
    ("F4", 0.5), ("F4", 0.5), ("E4", 0.5), ("E4", 0.5),
    ("D4", 0.5), ("D4", 0.5), ("C4", 1.0),
]
audio = concat(*[synth_note(midi_to_freq(NOTE_NAMES[n]), d, kind="piano") for n, d in mel])
write("09_melody_twinkle.wav", audio)

# ---- 10. realistic-ish: melody with vibrato + slight noise, voice-like ----
mel2 = [
    ("C4", 0.5), ("E4", 0.5), ("G4", 0.5), ("E4", 0.5),
    ("C4", 0.5), ("D4", 0.5), ("E4", 1.0),
]
parts = [synth_note(midi_to_freq(NOTE_NAMES[n]), d, kind="sustain", vibrato=True) for n, d in mel2]
audio = concat(*parts)
noise = np.random.default_rng(0).normal(0, 0.004, size=audio.shape)
write("10_realistic_voice.wav", audio + noise)

print("\nDone. Ground truth notes are documented in dev/gen_test_audio.py itself.")
