"""Attachments in chat: the upload, the message that carries them, what the model gets
(pictures as images when it takes them, a note when it does not), PDFs as text."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from PIL import Image

from openmuse.agent import Incoming, MuseAgent
from openmuse.config import LLMSettings, Settings, apply_app_settings
from openmuse.llm import MockLLM
from openmuse.llm import openai_chat as chat_mod
from openmuse.llm.openai_chat import OpenAIChatLLM
from openmuse.llm.openai_responses import _to_input_items
from openmuse.llm.prompt_tools import PromptToolAdapter
from openmuse.llm.vision import content_parts, image_data_url, says_no_images, without_images
from openmuse.schema import Attachment, LLMResponse, Message
from openmuse.sentinel import AuditLog, Sentinel
from openmuse.server.api import create_app
from openmuse.server.service import MuseService
from openmuse.tools import Files, Terminate, ToolCollection
from openmuse.ui import HeadlessUI


def make_pdf(text: str) -> bytes:
    """A one-page PDF with a text layer, by hand, with a proper xref."""
    content = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


PDF = make_pdf("Rent due on the 5th, 2400 CNY")


def png_bytes(w: int = 40, h: int = 30, color: str = "red", alpha: bool = False) -> bytes:
    im = Image.new("RGBA" if alpha else "RGB", (w, h), color)
    if alpha:
        im.putpixel((0, 0), (0, 0, 0, 0))
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def jpeg_bytes(w: int, h: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), "blue").save(out, format="JPEG", quality=90)
    return out.getvalue()


class FakeChat:
    """A Chat Completions endpoint that records requests and can refuse pictures."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.refuse_images = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        pictures = any(
            isinstance(m.get("content"), list)
            and any(p.get("type") == "image_url" for p in m["content"])
            for m in body["messages"]
        )
        if pictures and self.refuse_images:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Invalid content type. image_url is not supported",
                        "type": "invalid_request_error",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "I see a red square" if pictures else "text only",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def make(**kw: Any) -> AsyncOpenAI:
            kw["http_client"] = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
            return AsyncOpenAI(**kw)

        monkeypatch.setattr(chat_mod, "AsyncOpenAI", make)


@pytest.fixture()
def fake_chat(monkeypatch: pytest.MonkeyPatch) -> FakeChat:
    f = FakeChat()
    f.install(monkeypatch)
    return f


def llm_for(vision: str = "auto") -> OpenAIChatLLM:
    return OpenAIChatLLM(
        LLMSettings(api_key="k", base_url="http://chat.test/v1", stream=False, vision=vision)
    )  # type: ignore[arg-type]


# ----------------------------------------------------------------------------- pieces
def test_attachment_kinds_and_description():
    assert Attachment.kind_of("IMG_0042.JPG") == "image"
    assert Attachment.kind_of("lease.pdf") == "pdf"
    assert Attachment.kind_of("costs.csv") == "data"
    assert Attachment.kind_of("notes.md") == "text"
    assert Attachment.kind_of("archive.zip") == "other"
    assert Attachment(path="a/b.pdf", name="b.pdf", size=1536, kind="pdf").describe() == "PDF, 2 KB"
    assert (
        Attachment(path="a/p.jpg", name="p.jpg", size=3 * 1024 * 1024, kind="image").describe()
        == "image, 3.0 MB"
    )
    assert (
        Attachment(
            path="a/x.bin", name="x.bin", size=12, kind="other", mime="application/x-y"
        ).describe()
        == "application/x-y, 12 B"
    )


def test_images_are_scaled_and_encoded(tmp_path: Path):
    small = tmp_path / "small.png"
    small.write_bytes(png_bytes())
    url = image_data_url(str(small))
    assert url and url.startswith("data:image/png;base64,")  # small: as it is
    big = tmp_path / "photo.jpg"
    big.write_bytes(jpeg_bytes(4000, 3000))
    url = image_data_url(str(big))
    assert url and url.startswith("data:image/jpeg;base64,")
    import base64

    scaled = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(scaled.size) == 1568 and scaled.size == (1568, 1176)
    # a big PNG with transparency stays PNG when scaled
    alpha = tmp_path / "shot.png"
    alpha.write_bytes(png_bytes(2000, 1000, alpha=True))
    url = image_data_url(str(alpha))
    assert url and url.startswith("data:image/png;base64,")
    assert image_data_url(str(tmp_path / "gone.png")) is None


def test_content_parts_and_the_note(tmp_path: Path):
    pic = tmp_path / "a.png"
    pic.write_bytes(png_bytes())
    m = Message.user("what is this?", images=[str(pic), str(tmp_path / "missing.png")])
    parts = content_parts(m)
    assert (
        isinstance(parts, list) and parts[0]["type"] == "text" and parts[1]["type"] == "image_url"
    )
    assert "missing.png" in str(parts[0]["text"]) and "could not be included" in str(
        parts[0]["text"]
    )
    assert content_parts(Message.user("plain")) == "plain"
    # for the Responses API
    parts = content_parts(m, image_type="input_image")
    assert parts[0]["type"] == "input_text" and parts[1]["type"] == "input_image"
    # a model without vision gets told, per message
    stripped = without_images([Message.system("s"), m, Message.user("later")])
    assert stripped[1].images is None and "cannot be shown to you" in (stripped[1].content or "")
    assert "a.png" in (stripped[1].content or "") and stripped[2].content == "later"
    assert says_no_images("Invalid content type. image_url is not supported")
    assert says_no_images("this model does not support vision")
    assert not says_no_images("context length exceeded")


def test_responses_items_carry_pictures(tmp_path: Path):
    pic = tmp_path / "a.png"
    pic.write_bytes(png_bytes())
    _, items = _to_input_items([Message.user("look", images=[str(pic)])], with_images=True)
    assert items[0]["content"][1]["type"] == "input_image"
    _, items = _to_input_items([Message.user("look", images=[str(pic)])], with_images=False)
    assert items[0]["content"] == "look"


# ----------------------------------------------------------------------------- the provider
async def test_chat_sends_images_when_the_model_takes_them(fake_chat: FakeChat, tmp_path: Path):
    pic = tmp_path / "a.png"
    pic.write_bytes(png_bytes())
    llm = llm_for("auto")
    resp = await llm.ask([Message.system("s"), Message.user("what is this?", images=[str(pic)])])
    assert resp.content == "I see a red square" and llm.vision_available is True
    sent = fake_chat.requests[0]["messages"][1]["content"]
    assert sent[0] == {"type": "text", "text": "what is this?"}
    assert sent[1]["image_url"]["url"].startswith("data:image/png;base64,")
    await llm.close()


async def test_chat_falls_back_to_text_when_images_are_refused(fake_chat: FakeChat, tmp_path: Path):
    fake_chat.refuse_images = True
    pic = tmp_path / "a.png"
    pic.write_bytes(png_bytes())
    llm = PromptToolAdapter(llm_for("auto"), native_first=True)
    msgs = [Message.system("s"), Message.user("what is this?", images=[str(pic)])]
    resp = await llm.ask(msgs)
    assert resp.content == "text only" and llm.vision_available is False
    assert len(fake_chat.requests) == 2
    second = fake_chat.requests[1]["messages"][1]["content"]
    assert isinstance(second, str) and "cannot be shown to you" in second and "a.png" in second
    # from now on pictures are not even tried
    await llm.ask([*msgs, Message.assistant("ok"), Message.user("and this?", images=[str(pic)])])
    assert len(fake_chat.requests) == 3
    assert all(isinstance(m["content"], str) for m in fake_chat.requests[2]["messages"])
    await llm.inner.close()


async def test_chat_vision_off_and_on(fake_chat: FakeChat, tmp_path: Path):
    pic = tmp_path / "a.png"
    pic.write_bytes(png_bytes())
    off = llm_for("off")
    await off.ask([Message.user("look", images=[str(pic)])])
    assert isinstance(fake_chat.requests[0]["messages"][0]["content"], str)
    assert "does not take images" in fake_chat.requests[0]["messages"][0]["content"]
    assert off.vision_available is None
    fake_chat.refuse_images = True
    on = llm_for("on")
    import openai

    with pytest.raises(openai.BadRequestError):
        await on.ask([Message.user("look", images=[str(pic)])])
    await off.close()
    await on.close()


# ----------------------------------------------------------------------------- the agent
async def test_agent_message_with_attachments(settings: Settings):
    ws = settings.agent.workspace
    (ws / "attachments" / "2026-09-23").mkdir(parents=True)
    (ws / "attachments" / "2026-09-23" / "receipt.jpg").write_bytes(jpeg_bytes(50, 50))
    (ws / "attachments" / "2026-09-23" / "lease.pdf").write_bytes(PDF)
    files = [
        Attachment(
            path="attachments/2026-09-23/receipt.jpg", name="receipt.jpg", size=1200, kind="image"
        ),
        Attachment(path="attachments/2026-09-23/lease.pdf", name="lease.pdf", size=2, kind="pdf"),
    ]
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    llm = MockLLM([LLMResponse(content="Got them.")])
    agent = MuseAgent(
        settings,
        llm,
        ToolCollection(Terminate()),
        Sentinel(settings.sentinel, audit, ui),
        ui,
        audit,
    )
    await agent.run("file these", files=files)
    sent = llm.calls[0]["messages"][-1]
    assert sent.content.startswith(
        "file these\n\n[Attached files]\n- attachments/2026-09-23/receipt.jpg (image, 1 KB)"
    )
    assert "lease.pdf (PDF, 2 B)" in sent.content and "`files` action=read" in sent.content
    assert sent.images == [str(ws / "attachments/2026-09-23/receipt.jpg")]
    # attachments alone are a message too
    assert agent.user_message("", files[:1]).content.startswith("[Attached files]")
    assert agent.user_message("hi").images is None
    # the inbox carries them as well
    import asyncio

    agent.inbox = asyncio.Queue()
    agent.inbox.put_nowait(Incoming("and this", files[:1]))
    agent.inbox.put_nowait("plain")
    assert agent._drain_inbox() == 2
    assert agent.messages[-2].images and agent.messages[-1].content == "plain"


async def test_agent_tells_the_user_once_when_pictures_cannot_be_seen(settings: Settings):
    ws = settings.agent.workspace
    (ws / "a.png").write_bytes(png_bytes())
    files = [Attachment(path="a.png", name="a.png", size=1, kind="image")]
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    llm = MockLLM([LLMResponse(content="ok"), LLMResponse(content="ok again")])
    llm.vision_available = False  # what the provider sets after a refusal
    agent = MuseAgent(
        settings,
        llm,
        ToolCollection(Terminate()),
        Sentinel(settings.sentinel, audit, ui),
        ui,
        audit,
    )
    await agent.run("look", files=files)
    await agent.run("look again", files=files)
    warnings = [payload for kind, payload in ui.events if kind == "warn"]
    assert sum("does not take images" in w for w in warnings) == 1


def test_pdf_read_as_text(settings: Settings):
    ws = settings.agent.workspace
    (ws / "lease.pdf").write_bytes(PDF)
    tool = Files(workspace=ws)
    import asyncio

    out = asyncio.run(tool.execute(action="read", path="lease.pdf"))
    assert out.ok and "--- page 1 of 1 ---" in out.output and "Rent due on the 5th" in out.output
    # a PDF without a text layer says so
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with (ws / "scan.pdf").open("wb") as fh:
        w.write(fh)
    out = asyncio.run(tool.execute(action="read", path="scan.pdf"))
    assert out.ok and "no text layer" in out.output


# ----------------------------------------------------------------------------- the API
def events_of(
    client: TestClient, thread: str = "main", kind: str | None = None
) -> list[dict[str, Any]]:
    evs = client.get(f"/api/threads/{thread}/events").json()["events"]
    return [e for e in evs if kind is None or e["type"] == kind]


def wait_for(pred, timeout: float = 5.0):  # noqa: ANN001
    deadline = time.time() + timeout
    while time.time() < deadline:
        if value := pred():
            return value
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_upload_and_send_with_attachments(settings: Settings):
    settings.server.token = "secret-token"
    settings.server.max_upload_mb = 1
    llm = MockLLM([])
    service = MuseService(settings, llm=llm)
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        # a picture with an awkward name lands under attachments/<date>/ with a safe name
        r = client.post(
            "/api/files/upload?name=../../IMG 0042 (final).JPG",
            content=jpeg_bytes(20, 20),
            headers={"Content-Type": "image/jpeg"},
        )
        assert r.status_code == 200, r.text
        pic = r.json()
        assert (
            pic["kind"] == "image"
            and pic["name"] == "IMG 0042 (final).JPG"
            and pic["mime"] == "image/jpeg"
        )
        assert pic["path"].startswith("attachments/") and pic["path"].count("/") == 2
        assert (settings.agent.workspace / pic["path"]).is_file()
        # the same name again gets a suffix
        again = client.post(
            "/api/files/upload?name=IMG 0042 (final).JPG", content=jpeg_bytes(20, 20)
        ).json()
        assert again["name"] == "IMG 0042 (final) (2).JPG"
        # a Chinese name keeps its characters
        doc = client.post("/api/files/upload?name=租房合同.pdf", content=PDF).json()
        assert doc["name"] == "租房合同.pdf" and doc["kind"] == "pdf"
        # limits
        assert client.post("/api/files/upload?name=x.bin", content=b"").status_code == 400
        assert (
            client.post(
                "/api/files/upload?name=big.bin", content=b"x" * (1024 * 1024 + 1)
            ).status_code
            == 413
        )
        big_declared = client.post(
            "/api/files/upload?name=big.bin",
            content=b"x",
            headers={"Content-Length": str(2 * 1024 * 1024)},
        )
        assert big_declared.status_code == 413

        # send: attachments ride along; a message may be attachments alone
        llm.script.append(LLMResponse(content="A receipt and a lease."))
        r = client.post(
            "/api/threads/main/send", json={"text": "", "files": [pic["path"], doc["path"]]}
        )
        assert r.status_code == 200, r.text
        event = r.json()["event"]
        assert event["type"] == "user" and event["text"] == ""
        assert [f["name"] for f in event["files"]] == ["IMG 0042 (final).JPG", "租房合同.pdf"]
        assert event["files"][0]["kind"] == "image" and event["files"][1]["kind"] == "pdf"
        wait_for(lambda: events_of(client, kind="assistant"))
        sent = llm.calls[0]["messages"][-1]
        assert sent.content.startswith("[Attached files]") and "租房合同.pdf (PDF" in sent.content
        assert sent.images == [str(settings.agent.workspace.resolve() / pic["path"])]
        # the timeline keeps the attachments for the bubble
        user = events_of(client, kind="user")[0]
        assert len(user["files"]) == 2
        # the picture is served for the thumbnail
        assert client.get(f"/api/files/{pic['path']}").headers["content-type"] == "image/jpeg"

        # nothing at all, or a path outside the workspace, is refused
        assert (
            client.post("/api/threads/main/send", json={"text": "", "files": []}).status_code == 400
        )
        assert (
            client.post(
                "/api/threads/main/send", json={"text": "x", "files": ["../secret"]}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/threads/main/send", json={"text": "x", "files": ["attachments/nope.png"]}
            ).status_code
            == 400
        )

        # over the socket too
        llm.script.append(LLMResponse(content="seen"))
        with client.websocket_connect("/ws?token=secret-token") as ws:
            ws.receive_json()  # snapshot
            ws.send_json(
                {"kind": "send", "thread": "main", "text": "and this", "files": [pic["path"]]}
            )
            wait_for(lambda: len(events_of(client, kind="assistant")) == 2)
        assert llm.calls[1]["messages"][-1].images


def test_vision_setting_layers_from_the_app(settings: Settings):
    assert settings.llm.vision == "auto"
    apply_app_settings(settings, {"llm": {"vision": "off"}})
    assert settings.llm.vision == "off"
    apply_app_settings(settings, {"llm": {"vision": ""}})
    assert settings.llm.vision == "off"
