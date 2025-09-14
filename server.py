import asyncio
import os
import threading
import time
import webbrowser

import gradio as gr
from dotenv import load_dotenv

from pipecat.frames.frames import BotStoppedSpeakingFrame, StartFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.filters.stt_mute_filter import (
    STTMuteConfig,
    STTMuteFilter,
    STTMuteStrategy,
)
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.transports.null.audio import NullAudioTransport
try:  # optional local audio, may require PyAudio
    from pipecat.transports.local.audio import (
        LocalAudioTransport,
        LocalAudioTransportParams,
    )
except Exception:  # pragma: no cover - missing optional deps
    LocalAudioTransport = LocalAudioTransportParams = None


from script_gate import ScriptGate

load_dotenv()

GATEKEEPER_CONTENT_PACK: str = (
    """**REPLY ≤ 20 words. Two sentences max. No filler or meta.** ... (your full text) ..."""
)

# ---------------------------------------------------------------------------
# Model and service initialization
# ---------------------------------------------------------------------------

llm = GroqLLMService(
    api_key=os.getenv("GROQ_API_KEY"),
    model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    system_message=(
        GATEKEEPER_CONTENT_PACK
        + "\n\nReturn ONLY a single JSON object: "
          '{"say":"<the exact line to speak, ≤20 words>", "next_state":"<state id or empty>"} '
          "No markdown, no code fences, no extra text."
    ),
    params=GroqLLMService.InputParams(
        temperature=0.01,
        top_p=0.0,
        extra={"response_format": {"type": "json_object"}},
    ),
)

stt = DeepgramSTTService(
    api_key=os.getenv("DEEPGRAM_API_KEY"),
)

tts = CartesiaTTSService(
    api_key=os.getenv("CARTESIA_API_KEY"),
    voice_id=os.getenv("CARTESIA_VOICE_ID"),
)

HEADLESS = os.getenv("NO_AUDIO", "").lower() in ("1", "true", "yes")

if HEADLESS:
    transport = NullAudioTransport()
else:
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            input_device_index=int(os.getenv("AUDIO_IN_DEVICE_INDEX", "-1")),
            output_device_index=int(os.getenv("AUDIO_OUT_DEVICE_INDEX", "-1")),
        )
    )


# ---------------------------------------------------------------------------
# Script gating
# ---------------------------------------------------------------------------

state = {"id": "gatekeeper_open"}
SCRIPT = {
    "gatekeeper_open": "Hi, I'm Alex from Remember Church Directories—do you have a quick moment?",
    "value_prop": "We create free, photo-quality church directories; every family receives a complimentary eight-by-ten.",
    "ask_for_dm": "Could I please speak with the Pastor to share this brief gift idea?",
}

def required_line() -> str:
    return SCRIPT[state["id"]]

def set_next_state(ns: str) -> None:
    if ns in SCRIPT:
        state["id"] = ns

script_gate = ScriptGate(get_required_line=required_line, on_next_state=set_next_state, strict=True)

stt_mute = STTMuteFilter(

    config=STTMuteConfig(strategies={STTMuteStrategy.ON_BOT_SPEAKING})

)

pipeline = Pipeline([
    transport.input(),

    stt,
    stt_mute,

    llm,
    script_gate,
    tts,
    transport.output(),
])

# ---------------------------------------------------------------------------
# Runner helpers
# ---------------------------------------------------------------------------

async def _run_pipeline():
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=48000,
        ),
    )


    @task.event_handler("on_frame")
    async def _on_frame(frame):
        if isinstance(frame, BotStoppedSpeakingFrame):
            script_gate.release_next_state()

    runner = PipelineRunner()
    await task.queue_frame(StartFrame(allow_interruptions=True))
    await task.queue_frame(TTSSpeakFrame(required_line()))

    await runner.run(task)

def start_conversation():
    threading.Thread(target=lambda: asyncio.run(_run_pipeline()), daemon=True).start()
    return "Conversation started"

# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

with gr.Blocks() as ui:
    gr.Markdown("## Local Voice Agent (Deepgram STT + Groq LLM + Cartesia TTS)")
    status = gr.Textbox(label="Status")
    gr.Button("Start Conversation").click(fn=start_conversation, outputs=status)

    def _open():
        time.sleep(1)
        webbrowser.open("http://127.0.0.1:7860")

    threading.Thread(target=_open, daemon=True).start()

if __name__ == "__main__":
    ui.launch()
