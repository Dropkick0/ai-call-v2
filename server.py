import os, json, threading, time, webbrowser, asyncio
import requests
import gradio as gr
import pyaudio

from dotenv import load_dotenv

from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.groq.llm import GroqLLMService

from script_gate import ScriptGate

CARTESIA_API = "https://api.cartesia.ai/voices"  # list voices
CARTESIA_VERSION = os.getenv("CARTESIA_VERSION", "2025-04-16")  # current as of docs


def list_audio_devices():
    pa = pyaudio.PyAudio()
    ins, outs = [], []
    try:
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            name = f"[{i}] {info.get('name','?')} - {info.get('hostApi','')}"
            if int(info.get("maxInputChannels", 0)) > 0:
                ins.append((name, i))
            if int(info.get("maxOutputChannels", 0)) > 0:
                outs.append((name, i))
    finally:
        pa.terminate()
    # Return label list and default indices (-1 means "default device")
    return (
        ["Default (system)"] + [lbl for lbl, _ in ins],
        ["Default (system)"] + [lbl for lbl, _ in outs],
    )


def fetch_cartesia_voices():
    key = os.getenv("CARTESIA_API_KEY", "")
    if not key:
        return []
    headers = {
        "Authorization": f"Bearer {key}",
        "Cartesia-Version": CARTESIA_VERSION,
    }
    try:
        resp = requests.get(CARTESIA_API, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # Some versions return {"data":[...]} while older return a list—normalize
        items = data.get("data", data if isinstance(data, list) else [])
        voices = []
        for v in items:
            vid = v.get("id") or v.get("voice_id")
            name = v.get("name") or v.get("display_name") or vid
            if vid:
                voices.append((f"{name} ({vid})", vid))
        return voices
    except Exception:
        return []


NO_AUDIO = os.getenv("NO_AUDIO", "").lower() in ("1", "true", "yes")

load_dotenv()

GATEKEEPER_CONTENT_PACK: str = (
    """**REPLY ≤ 20 words. Two sentences max. No filler or meta.** ... (your full text) ..."""
)

# ---------------------------------------------------------------------------
# Model and service initialization
# ---------------------------------------------------------------------------

llm = GroqLLMService(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url=os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1"),
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


script_gate = ScriptGate(
    get_required_line=required_line, on_next_state=set_next_state, strict=True
)


runner_ref = {"runner": None, "task": None, "thread": None}


def _start_pipeline(input_idx, output_idx, voice_id):
    if NO_AUDIO:
        return "Headless mode; audio disabled."

    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.transports.local.audio import (
        LocalAudioTransport,
        LocalAudioTransportParams,
    )
    from pipecat.processors.filters.stt_mute_filter import (
        STTMuteConfig,
        STTMuteFilter,
        STTMuteStrategy,
    )
    from pipecat.frames.frames import BotStoppedSpeakingFrame
    from pipecat.services.cartesia.tts import CartesiaTTSService

    # Rebuild TTS with chosen voice
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id=voice_id or os.getenv("CARTESIA_VOICE_ID"),
    )

    # Device index parsing
    def _idx(label):
        if not label or label.startswith("Default"):
            return -1
        try:
            return int(label.split("]")[0].strip("["))
        except Exception:
            return -1

    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            input_device_index=_idx(input_idx),
            output_device_index=_idx(output_idx),
        )
    )

    # STT mute configured to mute only during bot speech
    stt_mute = STTMuteFilter(
        config=STTMuteConfig(strategies={STTMuteStrategy.ON_BOT_SPEAKING})
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            stt_mute,
            llm,
            script_gate,
            tts,
            transport.output(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=48000,
        ),
    )
    runner = PipelineRunner()

    @task.event_handler("on_frame")
    async def _on_frame(frame):
        if isinstance(frame, BotStoppedSpeakingFrame):
            script_gate.release_next_state()

    def _run():
        asyncio.run(_run_task(task, runner))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    runner_ref.update({"runner": runner, "task": task, "thread": t})
    return "Pipeline started. Say hello!"


async def _run_task(task, runner):
    from pipecat.frames.frames import StartFrame, TTSSpeakFrame

    await task.queue_frame(StartFrame(allow_interruptions=True))
    # speak the required opener immediately
    await task.queue_frame(TTSSpeakFrame(required_line()))
    await runner.run(task)


def _stop_pipeline():
    r = runner_ref["runner"]
    t = runner_ref["thread"]
    if r:
        r.stop()
    if t and t.is_alive():
        t.join(timeout=3)
    runner_ref.update({"runner": None, "task": None, "thread": None})
    return "Pipeline stopped."


# ------- Gradio UI -------
with gr.Blocks() as ui:
    gr.Markdown("## Local Voice Agent (Deepgram STT + Groq LLM + Cartesia TTS)")

    in_list, out_list = list_audio_devices()
    voices = fetch_cartesia_voices()

    dd_in = gr.Dropdown(
        choices=in_list,
        value=in_list[0] if in_list else None,
        label="Audio Input Device",
    )
    dd_out = gr.Dropdown(
        choices=out_list,
        value=out_list[0] if out_list else None,
        label="Audio Output Device",
    )
    dd_voice = gr.Dropdown(
        choices=[v[0] for v in voices],
        value=(voices[0][0] if voices else None),
        label="Cartesia Voice",
    )
    status = gr.Textbox(label="Status", interactive=False)

    def _refresh_voices():
        v = fetch_cartesia_voices()
        labels = [x[0] for x in v]
        return gr.update(choices=labels, value=(labels[0] if labels else None))

    btn_refresh = gr.Button("Refresh Voices")
    btn_start = gr.Button("Start Conversation", variant="primary")
    btn_stop = gr.Button("Stop Conversation")

    btn_refresh.click(fn=_refresh_voices, outputs=dd_voice)

    def _start_ui(in_label, out_label, voice_label):
        vid = ""
        vs = fetch_cartesia_voices()
        lut = {lbl: vid for (lbl, vid) in vs}
        vid = lut.get(voice_label, os.getenv("CARTESIA_VOICE_ID", ""))
        return _start_pipeline(in_label, out_label, vid)

    btn_start.click(fn=_start_ui, inputs=[dd_in, dd_out, dd_voice], outputs=status)
    btn_stop.click(fn=_stop_pipeline, outputs=status)

    # auto-open browser
    def _open():
        time.sleep(1)
        webbrowser.open("http://127.0.0.1:7860")

    threading.Thread(target=_open, daemon=True).start()

if __name__ == "__main__":
    ui.launch()

