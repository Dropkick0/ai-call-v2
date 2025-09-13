import json
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.frames.frames import LLMFullResponseEndFrame, LLMTextFrame, TTSSpeakFrame


class ScriptGate(FrameProcessor):
    """Validates LLM output against required script lines before TTS."""

    def __init__(self, get_required_line, on_next_state=None, strict: bool = True):
        super().__init__()
        self._buf = []
        self._get_required_line = get_required_line
        self._on_next_state = on_next_state or (lambda ns: None)
        self._strict = strict

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMTextFrame):
            self._buf.append(frame.text)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            raw = "".join(self._buf).strip()
            self._buf = []
            say, next_state = self._validate_or_fallback(raw)
            await self.push_frame(TTSSpeakFrame(say), FrameDirection.DOWNSTREAM)
            if next_state:
                self._on_next_state(next_state)
            return

        await self.push_frame(frame, direction)

    def _validate_or_fallback(self, raw: str):
        say = ""
        next_state = ""
        try:
            data = json.loads(raw)
            say = (data.get("say") or "").strip()
            next_state = (data.get("next_state") or "").strip()
        except Exception:
            pass

        required = (self._get_required_line() or "").strip()
        if self._strict:
            if not say or say.lower() != required.lower():
                say = required
        else:
            if not say:
                say = required
        return say, next_state
