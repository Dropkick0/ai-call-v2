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

        self._pending_next_state: str | None = None


    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMTextFrame):
            self._buf.append(frame.text)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            raw = "".join(self._buf).strip()
            self._buf = []
            say, next_state = self._validate_or_fallback(raw)

            self._pending_next_state = next_state or None
            await self.push_frame(TTSSpeakFrame(say), FrameDirection.DOWNSTREAM)

            return

        await self.push_frame(frame, direction)

    def _validate_or_fallback(self, raw: str):
        say = ""
        next_state = ""
        try:

            data = self._extract_json(raw)

            say = (data.get("say") or "").strip()
            next_state = (data.get("next_state") or "").strip()
        except Exception:
            pass

        required = (self._get_required_line() or "").strip()
        if self._strict:
            if not say or self._looks_meta(say) or self._norm(say) != self._norm(required):

                if say and self._norm(say) != self._norm(required):
                    print(f"\U0001F6E1\uFE0F Replaced off-script: {say!r} -> {required!r}")

                say = required
        else:
            if not say or self._looks_meta(say):
                say = required
        return say, next_state

    def _norm(self, s: str) -> str:
        return " ".join(
            s.replace("—", "-").replace("–", "-")
             .replace("’", "'").replace("“", '"').replace("”", '"')
             .split()
        ).lower()

    def _looks_meta(self, s: str) -> bool:
        sl = s.lower()

        return any(
            k in sl
            for k in [
                "option a",
                "option b",
                "say:",
                "meta:",
                "placeholder",
                "greeting +",
                "internal note",
            ]
        )

    def release_next_state(self):
        if self._pending_next_state:
            self._on_next_state(self._pending_next_state)
            self._pending_next_state = None


    def _extract_json(self, raw: str) -> dict:
        s = raw.strip()
        if s.startswith("```"):
            s = s.strip("`")
            if s.lower().startswith("json"):
                s = s[4:].lstrip()
        lo, hi = s.find("{"), s.rfind("}")
        if lo != -1 and hi != -1 and hi > lo:
            s = s[lo:hi + 1]
        return json.loads(s)

