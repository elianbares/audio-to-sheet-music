"""
AI Audio to Sheet Music Generator - Streamlit UI.

Keeps almost all real work in pipeline.py; this file is just the interface:
upload -> show progress -> show results -> offer downloads.
"""
import base64
import hashlib
import os
import tempfile
import traceback

import streamlit as st

import pipeline

MAX_UPLOAD_SECONDS_HINT = pipeline.MAX_AUDIO_SECONDS

st.set_page_config(
    page_title="AI Audio to Sheet Music Generator",
    page_icon="🎼",
    layout="centered",
)

st.title("AI Audio to Sheet Music Generator")
st.markdown("Upload a solo piano or voice recording and turn it into sheet music.")

st.caption(
    f"Works best with a single instrument or voice, one note at a time (or simple piano chords). "
    f"Recordings longer than {MAX_UPLOAD_SECONDS_HINT} seconds will be trimmed to the first "
    f"{MAX_UPLOAD_SECONDS_HINT} seconds."
)

if "result" not in st.session_state:
    st.session_state.result = None
if "result_file_hash" not in st.session_state:
    st.session_state.result_file_hash = None
if "error" not in st.session_state:
    st.session_state.error = None

uploaded_file = st.file_uploader("Upload a recording", type=["mp3", "wav", "m4a"])

generate_clicked = st.button("Generate Sheet Music", type="primary", disabled=uploaded_file is None)


def _run_transcription(file_bytes: bytes, suffix: str) -> dict:
    """Runs the full pipeline in a throwaway temp directory, shows live
    progress, and returns plain data (bytes + metadata) so nothing depends
    on files sticking around after this function returns."""
    status_box = st.status("Working on your sheet music...", expanded=True)

    def progress_fn(message: str) -> None:
        status_box.write(message)

    with tempfile.TemporaryDirectory(prefix="audio2sheet_") as tmp_dir:
        input_path = os.path.join(tmp_dir, f"input{suffix}")
        with open(input_path, "wb") as f:
            f.write(file_bytes)

        out_dir = os.path.join(tmp_dir, "out")

        try:
            result = pipeline.transcribe(input_path, out_dir, progress_fn=progress_fn)
        except pipeline.TranscriptionError as exc:
            status_box.update(label="Something went wrong", state="error")
            return {"error": str(exc), "technical_detail": exc.technical_detail}
        except Exception as exc:  # noqa: BLE001 - never let a raw traceback hit the main UI
            status_box.update(label="Something went wrong", state="error")
            return {
                "error": "Something unexpected went wrong while creating your sheet music.",
                "technical_detail": f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}",
            }

        with open(result.pdf_path, "rb") as f:
            pdf_bytes = f.read()
        with open(result.musicxml_path, "rb") as f:
            musicxml_bytes = f.read()
        with open(result.midi_path, "rb") as f:
            midi_bytes = f.read()

        status_box.update(label="Done!", state="complete")

        return {
            "error": None,
            "pdf": pdf_bytes,
            "musicxml": musicxml_bytes,
            "midi": midi_bytes,
            "detected_key": result.detected_key,
            "key_reliable": result.key_reliable,
            "time_signature": result.time_signature,
            "time_signature_reliable": result.time_signature_reliable,
            "tempo_bpm": result.tempo_bpm,
            "tempo_reliable": result.tempo_reliable,
            "note_count": result.note_count,
            "warnings": result.warnings,
        }


if generate_clicked and uploaded_file is not None:
    file_bytes = uploaded_file.getvalue()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    suffix = os.path.splitext(uploaded_file.name)[1].lower() or ".wav"

    if file_hash == st.session_state.result_file_hash and st.session_state.result is not None:
        # same file already processed (e.g. an unrelated widget triggered a
        # rerun) -- avoid redoing the expensive work.
        pass
    else:
        data = _run_transcription(file_bytes, suffix)
        st.session_state.result_file_hash = file_hash
        st.session_state.result = data

data = st.session_state.result

if data is not None:
    if data.get("error"):
        st.error(data["error"])
        if data.get("technical_detail"):
            with st.expander("Technical details (for debugging)"):
                st.code(data["technical_detail"])
    else:
        for w in data.get("warnings", []):
            st.info(w)

        st.subheader("Your sheet music")

        b64_pdf = base64.b64encode(data["pdf"]).decode("utf-8")
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{b64_pdf}" '
            f'width="100%" height="600" style="border:1px solid #ddd;border-radius:6px;">'
            f"</iframe>",
            unsafe_allow_html=True,
        )
        st.caption("If the preview above doesn't show in your browser, use the download button below instead.")

        details = []
        if data["key_reliable"] and data["detected_key"]:
            details.append(("Key", data["detected_key"]))
        if data["time_signature_reliable"]:
            details.append(("Time signature", data["time_signature"]))
        if data["tempo_reliable"]:
            details.append(("Tempo", f"{data['tempo_bpm']} BPM"))

        if details:
            cols = st.columns(len(details))
            for col, (label, value) in zip(cols, details):
                col.metric(label, value)

        st.divider()
        col1, col2, col3 = st.columns(3)
        col1.download_button(
            "Download PDF", data["pdf"], file_name="sheet_music.pdf", mime="application/pdf",
            use_container_width=True,
        )
        col2.download_button(
            "Download MusicXML", data["musicxml"], file_name="sheet_music.musicxml",
            mime="application/vnd.recordare.musicxml+xml", use_container_width=True,
        )
        col3.download_button(
            "Download MIDI", data["midi"], file_name="sheet_music.mid", mime="audio/midi",
            use_container_width=True,
        )

        st.caption(
            "This is an automatic transcription and won't be perfectly accurate, especially for "
            "expressive singing, fast passages, or complex chords. Treat it as a strong first draft."
        )

st.divider()
with st.expander("About this tool"):
    st.markdown(
        """
This tool listens to a recording, uses an AI model ([Basic Pitch](https://basicpitch.spotify.com/) by Spotify)
to guess which notes were played or sung, cleans up the timing into readable musical rhythm, and typesets it
into sheet music using [LilyPond](https://lilypond.org/).

It works best with:
- A single instrument or voice (not a full band or mixed recording)
- Clear, mostly in-tune notes
- Solo piano melodies, simple piano chords, or a single singing voice

It will struggle with:
- Multiple instruments or singers at once
- Heavy background noise or reverb
- Very fast or very ornamented passages
- Strong vibrato or pitch bending

Automatic transcription is genuinely hard, even for state-of-the-art AI -- treat the result as a helpful
starting point to clean up by hand, not a perfect copy of what was played.
"""
    )
