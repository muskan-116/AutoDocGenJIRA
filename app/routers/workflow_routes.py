from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.services.workflow_service import execute_workflow

workflow_router = APIRouter(prefix="/workflow", tags=["Workflow"])

@workflow_router.post("/run")
async def run_workflow(request: Request):
    try:
        # Just forward the request to the service
        result = await execute_workflow(request)
        return JSONResponse(result, status_code=200)

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
