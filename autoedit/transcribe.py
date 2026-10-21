"""Word-level transcription with faster-whisper (runs locally, no upload).

Output format used everywhere in the pipeline: a list of
{"w": "word", "s": start_seconds, "e": end_seconds} in source time.
"""
import json
from pathlib import Path


def transcribe(media_path, model_size="small", language=None):
    from faster_whisper import WhisperModel  # imported lazily: optional dependency

    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, _ = model.transcribe(
        str(media_path), word_timestamps=True, language=language,
        # keep disfluencies so the editor logic can see and cut them
        initial_prompt="Um, uh, like, you know, I mean.",
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"w": text, "s": round(w.start, 3), "e": round(w.end, 3)})
    return words


def load_or_transcribe(media_path, words_path=None, model_size="small", language=None):
    words_path = Path(words_path) if words_path else Path(str(media_path) + ".words.json")
    if words_path.exists():
        return json.loads(words_path.read_text())
    words = transcribe(media_path, model_size, language)
    words_path.write_text(json.dumps(words, indent=1))
    return words
