import asyncio
import os
import threading
import time
import webbrowser

import gradio as gr
from dotenv import load_dotenv
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

from script_gate import ScriptGate

load_dotenv()

# ---------------------------------------------------------------------------
# Model and service initialization
# ---------------------------------------------------------------------------

llm = GroqLLMService(
    api_key=os.getenv("GROQ_API_KEY"),
    model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
)

stt = DeepgramSTTService(
    api_key=os.getenv("DEEPGRAM_API_KEY"),
)

tts = CartesiaTTSService(
    api_key=os.getenv("CARTESIA_API_KEY"),
    voice_id=os.getenv("CARTESIA_VOICE_ID"),
)

transport = LocalAudioTransport(LocalAudioTransportParams())

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

pipeline = Pipeline([
    transport.input(),
    stt,
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
        params=PipelineParams(allow_interruptions=True),
    )
    runner = PipelineRunner()
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
