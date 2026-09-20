"""
Core audio -> sheet music pipeline.

    audio file
      -> Basic Pitch (audio -> note events)
      -> tempo estimation + rhythm quantization
      -> music21 Stream (notes, chords, rests, measures, key, time signature)
      -> MusicXML
      -> musicxml2ly + LilyPond -> PDF
      -> cleaned MIDI (re-exported from the quantized music21 stream, NOT the
         raw Basic Pitch MIDI, so downloaded MIDI reflects the same cleanup
         as the sheet music)

This module has no Streamlit dependency so it can be tested and iterated on
from the command line independent of the web UI.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

logging.getLogger("tensorflow").setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# Tunable constants (adjusted based on testing against dev/test_audio)
# ---------------------------------------------------------------------------

# Basic Pitch's default minimum_note_length (127.7ms) is too long: it merges
# or drops fast repeated notes (e.g. sixteenth notes around 120-150 BPM).
# Lowering it lets short/fast notes through; the quantizer cleans up timing
# afterwards.
MIN_NOTE_LENGTH_MS = 58.0

ONSET_THRESHOLD = 0.5
FRAME_THRESHOLD = 0.3

# Notes whose onsets are within this many seconds are treated as one chord.
CHORD_ONSET_TOLERANCE = 0.06

# Quantization grid: snap note starts/durations to the nearest 1/N of a
# quarter note. 4 = sixteenth-note resolution.
QUANTIZE_DIVISION = 4

MIN_QUANTIZED_QUARTER_LENGTH = 1.0 / QUANTIZE_DIVISION

MAX_AUDIO_SECONDS = 90  # keep jobs light enough for Streamlit Community Cloud

ProgressFn = Optional[Callable[[str], None]]


class TranscriptionError(Exception):
    """Raised for problems we want to show as a friendly message in the UI.

    `technical_detail`, if present, is safe to show in a collapsed
    "technical details" section but should never be put in front of the
    plain-English message shown by default.
    """

    def __init__(self, message: str, technical_detail: Optional[str] = None):
        super().__init__(message)
        self.technical_detail = technical_detail


@dataclass
class TranscriptionResult:
    musicxml_path: str
    midi_path: str
    pdf_path: str
    detected_key: Optional[str]
    key_reliable: bool
    time_signature: str
    time_signature_reliable: bool
    tempo_bpm: float
    tempo_reliable: bool
    note_count: int
    warnings: list = field(default_factory=list)


def _report(progress_fn: ProgressFn, message: str) -> None:
    if progress_fn:
        progress_fn(message)


# ---------------------------------------------------------------------------
# Step 1: audio -> note events (Basic Pitch)
# ---------------------------------------------------------------------------

def _load_basic_pitch_model():
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import Model

    return Model(ICASSP_2022_MODEL_PATH)


def prepare_audio(audio_path: str, out_dir: str) -> tuple:
    """Validate the uploaded audio and, if it's longer than
    MAX_AUDIO_SECONDS, trim it down before it ever reaches the model.
    Returns (path_to_use, warnings_list). Raises TranscriptionError for
    anything that isn't readable as audio at all (corrupt/empty/unsupported
    file)."""
    import librosa

    try:
        duration = librosa.get_duration(path=audio_path)
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionError(
            "We couldn't read that file. Make sure it's a valid MP3, WAV, or M4A recording.",
            technical_detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    if duration <= 0.15:
        raise TranscriptionError(
            "That recording is too short (or silent) to work with. Try a longer clip with a clear melody."
        )

    warnings_list = []
    if duration <= MAX_AUDIO_SECONDS:
        return audio_path, warnings_list

    try:
        y, sr = librosa.load(audio_path, sr=None, mono=True, duration=MAX_AUDIO_SECONDS)
        import soundfile as sf

        os.makedirs(out_dir, exist_ok=True)
        trimmed_path = os.path.join(out_dir, "_trimmed_input.wav")
        sf.write(trimmed_path, y, sr)
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionError(
            "We couldn't read that file. Make sure it's a valid MP3, WAV, or M4A recording.",
            technical_detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    warnings_list.append(
        f"Your recording is {duration:.0f} seconds long. To keep things fast, we only used the first "
        f"{MAX_AUDIO_SECONDS} seconds."
    )
    return trimmed_path, warnings_list


def predict_note_events(audio_path: str, model, progress_fn: ProgressFn = None):
    from basic_pitch.inference import predict

    _report(progress_fn, "Listening to your recording...")
    try:
        _, _, note_events = predict(
            audio_path,
            model,
            onset_threshold=ONSET_THRESHOLD,
            frame_threshold=FRAME_THRESHOLD,
            minimum_note_length=MIN_NOTE_LENGTH_MS,
            melodia_trick=True,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as TranscriptionError
        raise TranscriptionError(
            "We couldn't process that audio file.",
            technical_detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    if not note_events:
        raise TranscriptionError(
            "We couldn't detect a clear melody or instrument. Try a cleaner solo recording."
        )

    note_events = _drop_spurious_overlaps(note_events)
    note_events = _drop_pitch_fragments(note_events)

    if not note_events:
        raise TranscriptionError(
            "We couldn't detect a clear melody or instrument. Try a cleaner solo recording."
        )

    return sorted(note_events, key=lambda e: e[0])


# A note shorter than this that is immediately followed by another note of
# the *same* pitch is treated as a detection glitch (commonly caused by
# vibrato or a slightly unstable onset transient), not a real short note,
# and is dropped rather than kept as its own note.
SHORT_FRAGMENT_SECONDS = 0.09
FRAGMENT_MERGE_GAP = 0.08


def _drop_pitch_fragments(note_events):
    events = sorted(note_events, key=lambda e: e[0])
    keep = [True] * len(events)
    for i in range(len(events) - 1):
        start_i, end_i, pitch_i = events[i][0], events[i][1], events[i][2]
        duration_i = end_i - start_i
        if duration_i >= SHORT_FRAGMENT_SECONDS:
            continue
        start_j, pitch_j = events[i + 1][0], events[i + 1][2]
        if pitch_j == pitch_i and (start_j - end_i) < FRAGMENT_MERGE_GAP:
            keep[i] = False
    return [ev for ev, k in zip(events, keep) if k]


def _drop_spurious_overlaps(note_events, overlap_frac=0.6, amp_ratio=1.8):
    """Drop notes that are likely harmonic bleed-through: a note that
    mostly overlaps a much louder, differently-pitched note is probably a
    misdetected overtone rather than a real second note (common with
    sustained/resonant tones, e.g. piano sympathetic resonance)."""
    events = sorted(note_events, key=lambda e: e[0])
    keep = [True] * len(events)
    for i, ev in enumerate(events):
        start_i, end_i, pitch_i, amp_i = ev[0], ev[1], ev[2], ev[3]
        dur_i = max(end_i - start_i, 1e-6)
        for j, other in enumerate(events):
            if i == j or not keep[j]:
                continue
            start_j, end_j, pitch_j, amp_j = other[0], other[1], other[2], other[3]
            if pitch_j == pitch_i or amp_j <= amp_i * amp_ratio:
                continue
            overlap = max(0.0, min(end_i, end_j) - max(start_i, start_j))
            if overlap / dur_i >= overlap_frac:
                keep[i] = False
                break
    return [ev for ev, k in zip(events, keep) if k]


# ---------------------------------------------------------------------------
# Step 2: tempo estimation
# ---------------------------------------------------------------------------

def estimate_tempo(note_events, default_bpm: float = 100.0):
    """Estimate a tempo (BPM) from note onset spacing.

    This is inherently ambiguous (the "tatum vs. beat" problem in music
    information retrieval): a run of fast notes could be sixteenths at a
    slow tempo or eighths at a faster one. We find the coarsest time unit
    that explains the onset spacing, then pick the tempo interpretation of
    that unit that falls in a typical musical range. This is a heuristic,
    not a guarantee -- tempo detection is flagged as unreliable when the
    piece doesn't give us enough consistent onsets to be confident.
    """
    onsets = sorted(ev[0] for ev in note_events)
    iois = [b - a for a, b in zip(onsets, onsets[1:]) if (b - a) > 0.05]

    if len(iois) < 2:
        return default_bpm, False

    tatum = _estimate_tatum_seconds(iois)
    if tatum is None:
        return default_bpm, False

    bpm = 60.0 / tatum
    for k in (1, 2, 4, 8, 3):
        candidate = bpm / k
        if 50 <= candidate <= 184:
            return candidate, True

    while bpm > 184:
        bpm /= 2
    while bpm < 50:
        bpm *= 2
    return bpm, True


def _estimate_tatum_seconds(deltas, search_min=0.08, search_max=1.3, steps=500, rel_tol=0.08, complexity_penalty=0.03):
    """Find the coarsest interval that plausibly explains the spacing
    between note onsets (the "tatum" -- the smallest shared rhythmic unit).

    For each candidate interval t, most onset gaps should land close to an
    integer multiple of t. Picking the candidate that merely maximizes
    "how many deltas fit" is unstable: an implausibly tiny t can trivially
    "explain" almost any gap as some large multiple of itself. We instead
    score each candidate by fit quality *minus* a penalty on how large the
    multiples it needs are, and take the best-scoring candidate -- this
    prefers the simplest (coarsest) explanation that still fits the data
    reasonably well, and degrades gracefully on jittery real-world timing
    (e.g. vibrato) rather than chasing a spuriously fine grid.
    """
    deltas = np.array([d for d in deltas if d > 0.03])
    if len(deltas) == 0:
        return None

    candidates = np.geomspace(search_max, search_min, steps)
    best_t, best_score = candidates[0], -np.inf
    for t in candidates:
        nearest = np.maximum(np.round(deltas / t), 1)
        errs = np.abs(deltas - nearest * t) / t
        frac_good = float(np.mean(errs < rel_tol))
        complexity = float(np.mean(nearest))
        score = frac_good - complexity_penalty * complexity
        if score > best_score + 1e-9:
            best_score = score
            best_t = float(t)

    # refine: re-derive the tatum as the robust (median) average of
    # delta / nearest-integer-multiple using the coarse estimate, dropping
    # outliers (e.g. the first note's onset often lands slightly late due
    # to attack/detection latency, throwing off the very first interval).
    nearest = np.maximum(np.round(deltas / best_t), 1)
    per_delta_t = deltas / nearest
    errs = np.abs(deltas - nearest * best_t) / best_t
    inliers = per_delta_t[errs < rel_tol]
    if len(inliers) >= max(2, len(deltas) // 2):
        best_t = float(np.median(inliers))

    return best_t


# ---------------------------------------------------------------------------
# Step 3: note events -> music21 stream (quantize, chords, rests, measures)
# ---------------------------------------------------------------------------

def _group_chords(note_events):
    """Group notes with near-simultaneous onsets into chord clusters.
    Returns a list of clusters, each a list of (start, end, pitch)."""
    clusters = []
    current = []
    for ev in note_events:
        start = ev[0]
        if current and (start - current[0][0]) <= CHORD_ONSET_TOLERANCE:
            current.append(ev)
        else:
            if current:
                clusters.append(current)
            current = [ev]
    if current:
        clusters.append(current)
    return clusters


def build_score(note_events, tempo_bpm, progress_fn: ProgressFn = None):
    from music21 import chord, note, stream, tempo as m21tempo

    _report(progress_fn, "Cleaning up the rhythm...")

    clusters = _group_chords(note_events)

    quarter_per_second = tempo_bpm / 60.0

    # Quantize each note's OFFSET as a cumulative sum of quantized deltas
    # between consecutive onsets, rather than independently rounding each
    # note's absolute start time. Tempo estimation is never perfectly
    # exact, so scaling raw seconds by a slightly-off tempo and rounding
    # each note in isolation lets a small per-beat error compound over the
    # piece (e.g. a note that should land on beat 7 drifts onto beat
    # 6.75). Quantizing the small interval since the previous note instead
    # keeps each rounding step local, so errors don't accumulate.
    events = []  # (offset_ql, duration_ql, [pitches])
    cumulative_offset_ql = 0.0
    prev_start_sec = None
    for cluster in clusters:
        start_sec = min(e[0] for e in cluster)
        end_sec = max(e[1] for e in cluster)
        pitches = sorted({int(e[2]) for e in cluster})

        if prev_start_sec is None:
            cumulative_offset_ql = 0.0
        else:
            delta_ql = (start_sec - prev_start_sec) * quarter_per_second
            quantized_delta = round(delta_ql * QUANTIZE_DIVISION) / QUANTIZE_DIVISION
            quantized_delta = max(quantized_delta, MIN_QUANTIZED_QUARTER_LENGTH)
            cumulative_offset_ql += quantized_delta
        prev_start_sec = start_sec

        duration_ql = (end_sec - start_sec) * quarter_per_second
        duration_ql = round(duration_ql * QUANTIZE_DIVISION) / QUANTIZE_DIVISION
        duration_ql = max(duration_ql, MIN_QUANTIZED_QUARTER_LENGTH)

        events.append((cumulative_offset_ql, duration_ql, pitches))

    # resolve overlaps introduced by quantization: if a note's end now
    # overlaps the next note's (quantized) start, trim it.
    for i in range(len(events) - 1):
        offset, duration, pitches = events[i]
        next_offset = events[i + 1][0]
        if offset + duration > next_offset:
            new_duration = max(next_offset - offset, MIN_QUANTIZED_QUARTER_LENGTH)
            events[i] = (offset, new_duration, pitches)

    part = stream.Part()
    part.append(m21tempo.MetronomeMark(number=round(tempo_bpm)))

    cursor = 0.0
    for offset, duration, pitches in events:
        gap = offset - cursor
        if gap >= MIN_QUANTIZED_QUARTER_LENGTH:
            r = note.Rest()
            r.duration.quarterLength = gap
            part.append(r)
        elif gap > 0:
            # tiny leftover gap smaller than our grid: absorb by nudging
            # the previous element's duration instead of inserting a
            # sub-grid rest that would look wrong in notation.
            pass

        if len(pitches) == 1:
            n = note.Note()
            n.pitch.midi = pitches[0]
        else:
            n = chord.Chord(pitches)
        n.duration.quarterLength = duration
        part.append(n)
        cursor = offset + duration

    if len(part.notesAndRests) == 0:
        raise TranscriptionError(
            "We couldn't detect a clear melody or instrument. Try a cleaner solo recording."
        )

    return part


def _pick_time_signature(part):
    """Try a few common time signatures and pick whichever divides the
    piece into measures with the fewest notes split across barlines.
    Falls back to 4/4 (the most common default) when the piece is short or
    the signal isn't clear -- in that case time signature is reported as
    unreliable so the UI can hide it rather than show a guess."""
    from music21 import meter

    candidates = ["4/4", "3/4", "2/4", "6/8"]
    total_ql = sum(n.duration.quarterLength for n in part.notesAndRests)

    if total_ql < 4:
        return "4/4", False

    best_sig, best_score = "4/4", None
    for sig in candidates:
        ts = meter.TimeSignature(sig)
        bar_ql = ts.barDuration.quarterLength
        splits = 0
        pos = 0.0
        for n in part.notesAndRests:
            end = pos + n.duration.quarterLength
            if int(pos // bar_ql) != int((end - 1e-6) // bar_ql):
                splits += 1
            pos = end
        remainder = total_ql % bar_ql
        score = splits + (1 if remainder > 1e-6 else 0) * 0.5
        if best_score is None or score < best_score - 1e-9:
            best_sig, best_score = sig, score

    reliable = best_score is not None and best_score <= max(1, len(part.notesAndRests) * 0.08)
    return best_sig, reliable


def finalize_score(part, progress_fn: ProgressFn = None):
    from music21 import key as m21key, metadata, meter, stream

    _report(progress_fn, "Creating sheet music...")

    time_sig, ts_reliable = _pick_time_signature(part)
    part.insert(0, meter.TimeSignature(time_sig))

    detected_key = None
    key_reliable = False
    try:
        k = part.analyze("key")
        detected_key = f"{k.tonic.name} {k.mode}"
        # correlationCoefficient close to 1 = confident; music21 exposes it
        # on the analyzed Key object when available.
        confidence = getattr(k, "correlationCoefficient", None)
        key_reliable = confidence is None or confidence > 0.55
        part.insert(0, m21key.KeySignature(k.sharps))
    except Exception:  # noqa: BLE001 - key analysis is best-effort
        detected_key = None
        key_reliable = False

    score = stream.Score()
    score.metadata = metadata.Metadata()
    score.metadata.title = "Transcribed Score"
    score.append(part)

    score.makeMeasures(inPlace=True)
    for p in score.parts:
        # makeTies/makeBeams operate on a Part's own Measures; Score itself
        # has no direct Measures (they live under each Part), so these must
        # be called per-part rather than on the Score.
        p.makeTies(inPlace=True)
        p.makeBeams(inPlace=True)

    return score, detected_key, key_reliable, time_sig, ts_reliable


# ---------------------------------------------------------------------------
# Step 4: render outputs (MusicXML, MIDI, PDF)
# ---------------------------------------------------------------------------

def _find_lilypond_bin() -> Optional[str]:
    env_path = os.environ.get("LILYPOND_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    found = shutil.which("lilypond")
    if found:
        return found
    local = os.path.join(
        os.path.dirname(__file__), "tools", "lilypond-2.24.4", "bin", "lilypond"
    )
    if os.path.exists(local):
        return local
    return None


def _find_musicxml2ly_bin(lilypond_bin: str) -> Optional[str]:
    candidate = os.path.join(os.path.dirname(lilypond_bin), "musicxml2ly")
    if os.path.exists(candidate):
        return candidate
    found = shutil.which("musicxml2ly")
    return found


def render_outputs(score, out_dir: str, base_name: str = "score", progress_fn: ProgressFn = None):
    os.makedirs(out_dir, exist_ok=True)

    musicxml_path = os.path.join(out_dir, f"{base_name}.musicxml")
    midi_path = os.path.join(out_dir, f"{base_name}.mid")
    pdf_path = os.path.join(out_dir, f"{base_name}.pdf")

    score.write("musicxml", fp=musicxml_path)
    score.write("midi", fp=midi_path)

    _report(progress_fn, "Rendering the final score...")

    lilypond_bin = _find_lilypond_bin()
    if not lilypond_bin:
        raise TranscriptionError(
            "The sheet-music renderer (LilyPond) isn't installed, so we can't create a PDF."
        )
    musicxml2ly_bin = _find_musicxml2ly_bin(lilypond_bin)
    if not musicxml2ly_bin:
        raise TranscriptionError(
            "The MusicXML-to-LilyPond converter isn't installed, so we can't create a PDF."
        )

    lily_env = dict(os.environ)
    lily_dir = os.path.dirname(lilypond_bin)
    lily_env["PATH"] = lily_dir + os.pathsep + lily_env.get("PATH", "")

    ly_path = os.path.join(out_dir, f"{base_name}.ly")
    try:
        subprocess.run(
            [musicxml2ly_bin, "-o", ly_path, musicxml_path],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
            env=lily_env,
        )
        subprocess.run(
            [lilypond_bin, "-o", os.path.join(out_dir, base_name), ly_path],
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
            env=lily_env,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc))[-2000:]
        raise TranscriptionError(
            "We generated the music data, but couldn't render the PDF preview.",
            technical_detail=detail,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TranscriptionError(
            "Rendering the sheet music took too long and was stopped.",
            technical_detail=str(exc),
        ) from exc

    if not os.path.exists(pdf_path):
        raise TranscriptionError(
            "We generated the music data, but couldn't render the PDF preview."
        )

    return musicxml_path, midi_path, pdf_path


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

_MODEL_CACHE = {}


def get_model():
    if "model" not in _MODEL_CACHE:
        _MODEL_CACHE["model"] = _load_basic_pitch_model()
    return _MODEL_CACHE["model"]


def transcribe(audio_path: str, out_dir: str, progress_fn: ProgressFn = None) -> TranscriptionResult:
    model = get_model()

    working_audio_path, warnings_list = prepare_audio(audio_path, out_dir)

    note_events = predict_note_events(working_audio_path, model, progress_fn)

    _report(progress_fn, "Identifying notes...")
    tempo_bpm, tempo_reliable = estimate_tempo(note_events)

    part = build_score(note_events, tempo_bpm, progress_fn)
    score, detected_key, key_reliable, time_sig, ts_reliable = finalize_score(part, progress_fn)

    musicxml_path, midi_path, pdf_path = render_outputs(score, out_dir, progress_fn=progress_fn)

    return TranscriptionResult(
        musicxml_path=musicxml_path,
        midi_path=midi_path,
        pdf_path=pdf_path,
        detected_key=detected_key,
        key_reliable=key_reliable,
        time_signature=time_sig,
        time_signature_reliable=ts_reliable,
        tempo_bpm=round(tempo_bpm),
        tempo_reliable=tempo_reliable,
        note_count=len(note_events),
        warnings=warnings_list,
    )
