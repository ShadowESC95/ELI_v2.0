"""
ELI API Server – Enterprise edition.
Provides REST endpoints for chat and command execution.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import time
import uvicorn

from eli.brain.cognitive_engine import get_engine
from eli.brain.memory import get_memory

app = FastAPI(
    title="ELI Cognitive OS Agent API",
    description="Enterprise API for ELI – locally deployed, private, powerful.",
    version="1.0.0"
)

# ----------------------------------------------------------------------
# Request/Response Models
# ----------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    user_id: str = "default"
    session_id: Optional[str] = None
    stream: bool = False

class ChatResponse(BaseModel):
    response: str
    session_id: str
    user_id: str
    timestamp: float

class ExecuteRequest(BaseModel):
    action: str
    args: dict = {}
    user_id: str = "default"

class ExecuteResponse(BaseModel):
    ok: bool
    result: dict
    user_id: str
    timestamp: float

class StatusResponse(BaseModel):
    status: str
    version: str
    model: str
    uptime: float
    user_id: str

# ----------------------------------------------------------------------
# API Endpoints
# ----------------------------------------------------------------------
@app.get("/", tags=["Root"])
async def root():
    return {
        "service": "ELI Cognitive OS Agent",
        "version": "1.0.0",
        "documentation": "/docs"
    }

@app.get("/health", tags=["System"])
async def health():
    return {"status": "healthy"}

@app.post("/v1/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(request: ChatRequest):
    """Send a message to ELI and get a response."""
    try:
        engine = get_engine()
        session_id = request.session_id or str(int(time.time()))
        
        result = engine.process(
            request.message,
            source=f"api:{request.user_id}",
            stream=False
        )
        
        return ChatResponse(
            response=result.get("content", ""),
            session_id=session_id,
            user_id=request.user_id,
            timestamp=time.time()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/execute", response_model=ExecuteResponse, tags=["Commands"])
async def execute(request: ExecuteRequest):
    """Execute a direct ELI command (OPEN_APP, SCREENSHOT, etc.)."""
    try:
        from eli.tools.executor_enhanced import execute as exec_cmd
        
        result = exec_cmd(request.action, request.args)
        
        return ExecuteResponse(
            ok=result.get("ok", False),
            result=result,
            user_id=request.user_id,
            timestamp=time.time()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/status/{user_id}", response_model=StatusResponse, tags=["System"])
async def status(user_id: str):
    """Get ELI's current status for a user."""
    try:
        from eli.tools.executor_enhanced import get_status
        from eli.brain import config
        
        status_data = get_status()
        
        return StatusResponse(
            status="operational",
            version="1.0.0",
            model=config.get_gguf_model_path() or "unknown",
            uptime=time.time() - status_data.get("start_time", time.time()),
            user_id=user_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------------------------------------------------------------
# Run the server
# ----------------------------------------------------------------------
def main():
    uvicorn.run(
        "eli.api.server:app",
        host="0.0.0.0",
        port=8081,
        reload=True,
        log_level="info"
    )

if __name__ == "__main__":
    main()
