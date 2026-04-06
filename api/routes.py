"""
API Routes
----------
POST /api/v1/analyze         — async, returns job_id immediately
GET  /api/v1/results/{id}    — poll for completed verdict
GET  /api/v1/stream/{id}     — SSE stream of agent progress (for extension UI)
GET  /api/v1/archive         — paginated public verdict archive
"""
import asyncio
import json
import sqlite3
import uuid
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from pipeline import run_pipeline

router = APIRouter()

# ── SQLite setup ──────────────────────────────────────────────────────────────

DB_PATH = "verdicts.db"

def _init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS verdicts (
                id            TEXT PRIMARY KEY,
                raw_input     TEXT,
                input_type    TEXT,
                verdict       TEXT,
                confidence    REAL,
                summary       TEXT,
                red_flags     TEXT,
                timeline      TEXT,
                full_state    TEXT,
                created_at    TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_status (
                id      TEXT PRIMARY KEY,
                status  TEXT,         -- pending | running | done | error
                message TEXT
            )
        """)

_init_db()

# In-memory SSE event queues per job_id
_sse_queues: dict[str, asyncio.Queue] = {}


# ── Request / Response models ─────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    input: str      # image URL, article URL, or raw text claim


class AnalyzeResponse(BaseModel):
    job_id: str
    message: str


class VerdictResponse(BaseModel):
    job_id:           str
    status:           str
    verdict:          str | None
    confidence_score: float | None
    summary:          str | None
    red_flags:        list[str]
    timeline:         list[dict]
    input_type:       str | None
    created_at:       str | None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO job_status (id, status, message) VALUES (?, ?, ?)",
            (job_id, "pending", "Job queued"),
        )

    _sse_queues[job_id] = asyncio.Queue()
    background_tasks.add_task(_run_job, job_id, req.input)

    return AnalyzeResponse(job_id=job_id, message="Analysis started. Poll /results/{job_id} or stream /stream/{job_id}.")


@router.get("/results/{job_id}", response_model=VerdictResponse)
async def get_results(job_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        # Check status
        row = conn.execute("SELECT status, message FROM job_status WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        status, message = row

        if status != "done":
            return VerdictResponse(
                job_id=job_id, status=status,
                verdict=None, confidence_score=None, summary=message,
                red_flags=[], timeline=[], input_type=None, created_at=None,
            )

        verdict_row = conn.execute(
            "SELECT verdict, confidence, summary, red_flags, timeline, input_type, created_at FROM verdicts WHERE id = ?",
            (job_id,),
        ).fetchone()

        if not verdict_row:
            raise HTTPException(status_code=404, detail="Verdict not stored yet")

        v, conf, summary, flags_json, timeline_json, input_type, created_at = verdict_row
        return VerdictResponse(
            job_id=job_id, status="done",
            verdict=v,
            confidence_score=conf,
            summary=summary,
            red_flags=json.loads(flags_json or "[]"),
            timeline=json.loads(timeline_json or "[]"),
            input_type=input_type,
            created_at=created_at,
        )


@router.get("/stream/{job_id}")
async def stream_events(job_id: str):
    """SSE endpoint — browser extension listens here for live agent updates."""
    if job_id not in _sse_queues:
        raise HTTPException(status_code=404, detail="Job not found or already completed.")

    async def _generator() -> AsyncGenerator[str, None]:
        queue = _sse_queues[job_id]
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=60.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "done":
                    break
            except asyncio.TimeoutError:
                yield "data: {\"type\": \"heartbeat\"}\n\n"

    return StreamingResponse(_generator(), media_type="text/event-stream")


@router.get("/archive")
async def archive(page: int = 1, per_page: int = 20):
    offset = (page - 1) * per_page
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, raw_input, input_type, verdict, confidence, created_at FROM verdicts ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0]

    return {
        "page": page, "per_page": per_page, "total": total,
        "results": [
            {"id": r[0], "input": r[1][:80], "input_type": r[2], "verdict": r[3], "confidence": r[4], "created_at": r[5]}
            for r in rows
        ],
    }


# ── Background job ─────────────────────────────────────────────────────────────

async def _run_job(job_id: str, raw_input: str):
    queue = _sse_queues.get(job_id)

    def _emit(agent: str, status: str, detail: str = ""):
        if queue:
            asyncio.get_event_loop().call_soon_threadsafe(
                queue.put_nowait,
                {"type": "agent_update", "agent": agent, "status": status, "detail": detail},
            )

    _update_status(job_id, "running", "Pipeline started")
    _emit("triage", "running")

    try:
        # Run the blocking LangGraph pipeline in a thread pool
        loop = asyncio.get_event_loop()
        state = await loop.run_in_executor(None, run_pipeline, raw_input)

        _emit("forensics",      "done", _signal_detail(state, "ela_signal"))
        _emit("vision",         "done", _signal_detail(state, "groq_vision_signal"))
        _emit("reverse_search", "done", _signal_detail(state, "reverse_search_signal"))
        _emit("fact_check",     "done", _signal_detail(state, "fact_check_signal"))
        _emit("ai_text",        "done", _signal_detail(state, "ai_text_signal"))
        _emit("synthesis",      "done", f"Verdict: {state.get('verdict')} ({state.get('confidence_score')}%)")

        _store_verdict(job_id, state)
        _update_status(job_id, "done", "Analysis complete")

        if queue:
            queue.put_nowait({"type": "done", "verdict": state.get("verdict"), "confidence": state.get("confidence_score")})

    except Exception as e:
        _update_status(job_id, "error", str(e))
        if queue:
            queue.put_nowait({"type": "error", "message": str(e)})
    finally:
        _sse_queues.pop(job_id, None)


def _signal_detail(state, key: str) -> str:
    sig = state.get(key)
    if not sig:
        return "skipped"
    return sig.get("details", "")[:80]


def _update_status(job_id: str, status: str, message: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE job_status SET status = ?, message = ? WHERE id = ?",
            (status, message, job_id),
        )


def _store_verdict(job_id: str, state):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO verdicts
               (id, raw_input, input_type, verdict, confidence, summary, red_flags, timeline, full_state, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                state.get("raw_input", "")[:500],
                state.get("input_type", ""),
                state.get("verdict"),
                state.get("confidence_score"),
                state.get("summary", ""),
                json.dumps(state.get("red_flags", [])),
                json.dumps(state.get("timeline", [])),
                json.dumps({k: str(v) for k, v in state.items() if k not in ("image_bytes",)}),
                datetime.utcnow().isoformat(),
            ),
        )
        
@router.post("/debug")
async def debug(req: AnalyzeRequest):
    try:
        from pipeline import run_pipeline
        state = run_pipeline(req.input)
        return {
            "input_type":    state.get("input_type"),
            "image_bytes":   bool(state.get("image_bytes")),
            "article_text":  (state.get("article_text") or "")[:200],
            "claims":        state.get("_extracted_claims"),
            "verify":        state.get("_verification_results"),
            "claim_verify_signal": state.get("_claim_verify_signal"),
            "error":         state.get("error"),
            "ela":           state.get("ela_signal"),
            "cnndetect":     state.get("cnndetect_signal"),
            "vision":        state.get("groq_vision_signal"),
            "reverse":       state.get("reverse_search_signal"),
            "fact_check":    state.get("fact_check_signal"),
            "ai_text":       state.get("ai_text_signal"),
            "verdict":       state.get("verdict"),
            "confidence":    state.get("confidence_score"),
            "red_flags":     state.get("red_flags"),
        }
    except Exception as e:
        return {"error": str(e)}