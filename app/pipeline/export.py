"""Exports: diagram images (rendered by bpmn-js, same as the editor) and a written SOP."""

import contextlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from app.core.config import get_settings
from app.models.process import GATEWAY_TYPES, TASK_TYPES, ProcessModel
from app.pipeline.convert import _clean, _columns

VIEWER_JS = Path(__file__).parent.parent / "static" / "vendor" / "bpmn-viewer.production.min.js"  # bpmn-js 18.29.1


class ExportError(RuntimeError):
    pass


# Playwright's sync API is bound to the thread that started it, so one dedicated thread owns
# a warm browser and every render runs there. Renders are serialized (one at a time), which
# is plenty for exports; raise max_workers and keep one browser per thread if it isn't.
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bpmn-export")
_STATE: dict[str, Any] = {}  # touched only from the export thread; the browser exits with the process
RENDER_TIMEOUT_S = 60


def _page() -> Any:
    from playwright.sync_api import sync_playwright

    browser = _STATE.get("browser")
    if browser is None or not browser.is_connected():
        if "playwright" not in _STATE:
            _STATE["playwright"] = sync_playwright().start()
        channel = get_settings().export_browser_channel
        chromium = _STATE["playwright"].chromium
        browser = chromium.launch(channel=channel) if channel else chromium.launch()
        _STATE["browser"] = browser
    return browser.new_page(device_scale_factor=2)


def _render(bpmn_xml: str, fmt: str) -> bytes:
    from playwright.sync_api import Error

    for attempt in (1, 2):  # a crashed browser gets one relaunch
        page = None
        try:
            page = _page()
            page.set_content('<div id="c" style="width:1600px;height:1000px"></div>')
            page.add_script_tag(path=str(VIEWER_JS))  # bundled: no CDN call from the server
            svg: str = page.evaluate(
                """async (xml) => {
                    const viewer = new BpmnJS({ container: '#c' });
                    const { warnings } = await viewer.importXML(xml);
                    if (warnings.length) console.warn(warnings);
                    return (await viewer.saveSVG()).svg;
                }""",
                bpmn_xml,
            )
            if fmt == "svg":
                return svg.encode()
            page.set_content(f'<body style="margin:0;background:#fff">{svg}</body>')
            png: bytes = page.locator("svg").first.screenshot(type="png")
            return png
        except Error as e:
            _STATE.pop("browser", None)
            if attempt == 2:
                raise ExportError(f"Diagram rendering failed: {e.message.splitlines()[0]}") from e
        finally:
            if page is not None:
                with contextlib.suppress(Error):  # the browser may already be gone
                    page.close()
    raise AssertionError("unreachable")


def render_image(bpmn_xml: str, fmt: Literal["svg", "png"]) -> bytes:
    """Render with bpmn-js in headless Chromium, so exports look exactly like the editor.

    Uses Playwright's Chromium (`playwright install chromium`), or a locally installed browser
    if EXPORT_BROWSER_CHANNEL is set (e.g. "chrome"). The browser stays warm between exports.
    """
    return _EXECUTOR.submit(_render, bpmn_xml, fmt).result(timeout=RENDER_TIMEOUT_S)


def _pdf(page_html: str) -> bytes:
    from playwright.sync_api import Error

    page = None
    try:
        page = _page()
        page.set_content(page_html)
        pdf: bytes = page.pdf(format="A4", margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"})
        return pdf
    except Error as e:
        _STATE.pop("browser", None)
        raise ExportError(f"PDF rendering failed: {e.message.splitlines()[0]}") from e
    finally:
        if page is not None:
            with contextlib.suppress(Error):
                page.close()


def render_pdf(page_html: str) -> bytes:
    """Print an HTML page to PDF in the same warm headless browser as the diagram renders."""
    return _EXECUTOR.submit(_pdf, page_html).result(timeout=RENDER_TIMEOUT_S)


def _ts(seconds: float | None) -> str:
    return "" if seconds is None else f" @ {int(seconds // 60)}:{int(seconds % 60):02d}"


def sop_markdown(model: ProcessModel, segments: dict[str, dict[str, Any]], sources: dict[str, str]) -> str:
    """A written standard operating procedure from the model, every step citing its quotes.

    `segments`: segment id (as cited by the model) -> {speaker, text, start_ts}.
    `sources`: transcript id -> filename, for merged maps whose citations are `<tid>:<sid>`.
    """
    lanes, nodes, flows = _clean(model)
    lane_name = dict(lanes)
    col, _ = _columns(nodes, flows)
    lane_order = {lid: i for i, (lid, _) in enumerate(lanes)}
    ordered = sorted(nodes, key=lambda n: (col[n.id], lane_order[n.lane_id]))
    number = {n.id: i for i, n in enumerate((n for n in ordered if n.type in TASK_TYPES), 1)}
    out_flows = defaultdict(list)
    for f in flows:
        out_flows[f.source_id].append(f)
    name = {n.id: n.name for n in nodes}

    def ref(node_id: str) -> str:
        return f"step {number[node_id]} ({name[node_id]})" if node_id in number else (name[node_id] or "next")

    def quotes(ids: list[str]) -> list[str]:
        lines = []
        for sid in ids:
            seg = segments.get(sid)
            where = sources.get(sid.split(":")[0], "") if ":" in sid else ""
            if seg is None:
                lines.append(f"   > _[{sid}] source text no longer available_")
                continue
            lines.append(
                f"   > “{seg['text']}”  \n   > — {seg.get('speaker') or 'Unknown'}"
                f"{', ' + where if where else ''}{_ts(seg.get('start_ts'))} [{sid}]"
            )
        return lines

    md = [
        f"# {model.name}",
        "",
        "_Standard operating procedure generated from meeting transcripts. "
        "Quotes show where each step came from; review before publishing._",
        "",
    ]
    md += ["## Roles", ""] + [f"- **{lane_name[lid]}**" for lid, _ in lanes if any(n.lane_id == lid for n in nodes)]
    triggers = [n.name for n in nodes if n.type == "start_event"]
    if triggers:
        md += ["", f"**Starts when:** {'; '.join(t or 'the process starts' for t in triggers)}"]

    md += ["", "## Procedure", ""]
    for n in ordered:
        nxt = out_flows[n.id]
        if n.type in TASK_TYPES:
            flags = (
                " _(added manually, no transcript source)_"
                if n.user_added
                else (f" _(confidence {n.confidence:.0%})_" if n.confidence < 0.6 else "")
            )
            md.append(f"{number[n.id]}. **{n.name}** — {lane_name[n.lane_id]}{flags}")
            md += quotes(n.source_segment_ids)
        elif n.type == "exclusive_gateway" and len(nxt) > 1:
            md.append(f"- **Decision ({lane_name[n.lane_id]}): {n.name or 'which path?'}**")
            md += [f"   - If {f.condition or '(condition not stated)'}: go to {ref(f.target_id)}" for f in nxt]
            md += quotes(n.source_segment_ids)
        elif n.type == "parallel_gateway" and len(nxt) > 1:
            md.append("- **In parallel:** " + ", ".join(ref(f.target_id) for f in nxt))
        elif n.type == "end_event":
            md.append(f"- **Outcome:** {n.name or 'process ends'}")
        elif n.type in GATEWAY_TYPES:
            continue  # joins need no prose

    if model.open_questions:
        md += ["", "## Open questions", ""] + [f"- {q.question}" for q in model.open_questions]
    return "\n".join(md) + "\n"
