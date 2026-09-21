"""
Dev-only test harness: runs the real pipeline against every file in
dev/test_audio and dumps MusicXML/MIDI/PDF + a PNG preview + a text summary
into dev/test_output/<name>/ so we can inspect results by hand.
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LILYPOND_PATH"] = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools", "lilypond-2.24.4", "bin", "lilypond",
)

import pipeline  # noqa: E402

TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_audio")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_output")

only = sys.argv[1] if len(sys.argv) > 1 else None

files = sorted(f for f in os.listdir(TEST_DIR) if f.endswith(".wav"))
if only:
    files = [f for f in files if only in f]

for fname in files:
    print(f"\n=== {fname} ===")
    audio_path = os.path.join(TEST_DIR, fname)
    out_dir = os.path.join(OUT_DIR, os.path.splitext(fname)[0])
    try:
        result = pipeline.transcribe(audio_path, out_dir, progress_fn=lambda m: print(f"  [{m}]"))
    except pipeline.TranscriptionError as e:
        print(f"  FAILED: {e}")
        continue
    except Exception as e:  # noqa: BLE001
        print(f"  CRASHED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        continue

    print(f"  notes detected: {result.note_count}")
    print(f"  tempo: {result.tempo_bpm} bpm (reliable={result.tempo_reliable})")
    print(f"  key: {result.detected_key} (reliable={result.key_reliable})")
    print(f"  time signature: {result.time_signature} (reliable={result.time_signature_reliable})")
    print(f"  pdf: {result.pdf_path}")

    # render a PNG preview of page 1 for visual inspection
    try:
        import fitz
        doc = fitz.open(result.pdf_path)
        png_path = os.path.join(out_dir, "preview.png")
        doc[0].get_pixmap(dpi=150).save(png_path)
        print(f"  preview: {png_path}")
    except Exception as e:  # noqa: BLE001
        print(f"  (preview render failed: {e})")
