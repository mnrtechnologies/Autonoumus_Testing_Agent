"""
Robo-Tester v3.x – FastAPI Control Plane (Single File)

Run with:
    uvicorn app:app --reload
"""

import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Literal
from threading import Thread
from uuid import uuid4
from dotenv import load_dotenv
from fastapi import WebSocket, WebSocketDisconnect
import base64
import asyncio
from fastapi.middleware.cors import CORSMiddleware
import sys
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from engines.orchestrator import Orchestrator

load_dotenv()


# =====================================================================
# Pydantic Schemas
# =====================================================================

class CheckingStartRequest(BaseModel):
    base_url: str

class CheckingResponse(BaseModel):
    status: str
    message: str

class StartTestRequest(BaseModel):
    mode: Literal["whitebox", "blackbox"]
    url: str
    goal: str
    steps: Optional[List[str]] = []

class StartTestResponse(BaseModel):
    test_id: str
    status: str

class TestStatusResponse(BaseModel):
    test_id: str
    status: str
    current_step: int
    max_steps: int
    last_action: Optional[str]
    assertions: List[str] = [] 
    summary: Optional[str] = None

class UserInputRequest(BaseModel):
    element_id: str
    value: str

class DiscoverRequest(BaseModel):
    target_url: str
    login_url: Optional[str] = None
    requires_auth: bool = True

# =====================================================================
# In-Memory Test Registry (can later move to Redis / DB)
# =====================================================================

TESTS: Dict[str, dict] = {}

def create_test(orchestrator: Orchestrator) -> str:
    test_id = str(uuid4())
    TESTS[test_id] = {
        "orchestrator": orchestrator,
        "status": "running",
        "report": None
    }
    return test_id

CHECKING_JOBS: Dict[str, dict] = {}

def create_checking_job(pipeline) -> str:
    job_id = str(uuid4())
    CHECKING_JOBS[job_id] = {
        "pipeline": pipeline,
        "status": "running"
    }
    return job_id

# =====================================================================
# FastAPI App
# =====================================================================

app = FastAPI(
    title="Robo-Tester API",
    version="3.1",
    description="API wrapper for Robo-Tester Autonomous Web Testing Agent"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    print("⚠️  WARNING: OPENAI_API_KEY is not set")

# =====================================================================
# Health Check
# =====================================================================

@app.get("/health")
def health():
    return {"status": "ok"}

# =====================================================================
# Start Test (Whitebox / Blackbox)
# =====================================================================

@app.post("/tests/start", response_model=StartTestResponse)
def start_test(payload: StartTestRequest):
    orchestrator = Orchestrator(
        api_key=OPENAI_API_KEY,
        headless=True
    )

    test_id = create_test(orchestrator)

    def run_test():
        try:
            goal = (
                payload.goal
                if payload.mode == "blackbox"
                else "\n".join(payload.steps) if payload.steps else payload.goal
            )

            result = orchestrator.run(
                url=payload.url,
                goal=goal
            )

            TESTS[test_id]["status"] = "completed"
            TESTS[test_id]["report"] = result

        except Exception as e:
            TESTS[test_id]["status"] = "failed"
            TESTS[test_id]["report"] = {"error": str(e)}

    Thread(target=run_test, daemon=True).start()

    return StartTestResponse(
        test_id=test_id,
        status="running"
    )

# =====================================================================
# Get Test Status (Live Progress)
# =====================================================================

# app.py

@app.get("/tests/{test_id}/status", response_model=TestStatusResponse)
def get_test_status(test_id: str):
    if test_id not in TESTS:
        raise HTTPException(status_code=404, detail="Test not found")

    orch: Orchestrator = TESTS[test_id]["orchestrator"]
    status = TESTS[test_id]["status"]

    return TestStatusResponse(
        test_id=test_id,
        status=status,
        current_step=orch.step_count,
        max_steps=orch.max_steps,
        last_action=orch.action_history[-1] if orch.action_history else None,
        assertions=orch.assertions,
        summary=orch.summary if status == "completed" else None
    )

# =====================================================================
# Get Final Test Report
# =====================================================================

@app.get("/tests/{test_id}/report")
def get_test_report(test_id: str):
    if test_id not in TESTS:
        raise HTTPException(status_code=404, detail="Test not found")

    if TESTS[test_id]["status"] != "completed":
        return {
            "status": TESTS[test_id]["status"],
            "message": "Test not completed yet"
        }

    return TESTS[test_id]["report"]

# =====================================================================
# Provide User Input (OTP / Form Fields)
# =====================================================================

@app.post("/tests/{test_id}/input")
def provide_user_input(test_id: str, payload: UserInputRequest):
    orch: Orchestrator = TESTS[test_id]["orchestrator"]

    orch.collected_credentials[payload.element_id] = payload.value

    orch.waiting_for_input = False
    orch.waiting_input_payload = None

    return {"status": "resumed"}

@app.get("/tests/{test_id}/waiting")
def check_waiting_state(test_id: str):
    if test_id not in TESTS:
        raise HTTPException(status_code=404)

    orch = TESTS[test_id]["orchestrator"]

    if orch.waiting_for_input:
        return {
            "waiting": True,
            "payload": orch.waiting_input_payload
        }

    return {"waiting": False}


# =====================================================================
# List All Tests
# =====================================================================

@app.get("/tests")
def list_tests():
    return {
        test_id: {
            "status": data["status"]
        }
        for test_id, data in TESTS.items()
    }


# =====================================================================
# Websocket Streaming (Screenshots)
# =====================================================================

@app.websocket("/ws/tests/{test_id}")
async def stream_browser(websocket: WebSocket, test_id: str):
    await websocket.accept()

    if test_id not in TESTS:
        await websocket.send_json({"error": "Invalid test_id"})
        await websocket.close()
        return

    orch = TESTS[test_id]["orchestrator"]

    try:
        while True:
            # Send latest screenshot if available
            screenshot_path = getattr(orch, "latest_screenshot", None)

            if orch.step_count > 0 and screenshot_path and os.path.exists(screenshot_path):
                with open(screenshot_path, "rb") as f:
                    img_bytes = f.read()

                await websocket.send_json({
                    "type": "frame",
                    "image": base64.b64encode(img_bytes).decode("utf-8"),
                    "step": orch.step_count
                })

            await asyncio.sleep(0.3)  # ~3 FPS (safe)
    except WebSocketDisconnect:
        print("🔌 WebSocket disconnected")

#==========================================================================
# CHECKING.PY ENDPOINTS
#====================================================================================================
from checking import CheckingPipeline

@app.post("/checking/start")
def start_checking(payload: CheckingStartRequest):

    pipeline = CheckingPipeline(base_url=payload.base_url)
    job_id = create_checking_job(pipeline)

    def run_pipeline():
        try:
            asyncio.run(pipeline.run())
            CHECKING_JOBS[job_id]["status"] = pipeline.status
        except Exception as e:
            CHECKING_JOBS[job_id]["status"] = "failed"

    Thread(target=run_pipeline, daemon=True).start()

    return {
        "job_id": job_id,
        "status": "running"
    }


@app.get("/checking/{job_id}/status")
def checking_status(job_id: str):
    if job_id not in CHECKING_JOBS:
        raise HTTPException(status_code=404)

    pipeline = CHECKING_JOBS[job_id]["pipeline"]

    return {
        "status": pipeline.status,
        "current_url": pipeline.current_url,
        "total_urls": pipeline.total_urls,
        "completed_urls": pipeline.completed_urls,
        "error": pipeline.error
    }

@app.websocket("/ws/checking/{job_id}")
async def stream_checking_browser(websocket: WebSocket, job_id: str):
    await websocket.accept()

    if job_id not in CHECKING_JOBS:
        await websocket.send_json({"error": "Invalid job_id"})
        await websocket.close()
        return

    pipeline = CHECKING_JOBS[job_id]["pipeline"]

    try:
        while True:
            screenshot_path = getattr(pipeline, "latest_screenshot", None)

            if screenshot_path and os.path.exists(screenshot_path):
                with open(screenshot_path, "rb") as f:
                    img_bytes = f.read()

                await websocket.send_json({
                    "type": "frame",
                    "image": base64.b64encode(img_bytes).decode("utf-8"),
                    "current_url": pipeline.current_url,
                    "completed": pipeline.completed_urls,
                    "total": pipeline.total_urls
                })

            await asyncio.sleep(0.3)

    except WebSocketDisconnect:
        print("🔌 Checking WebSocket disconnected")