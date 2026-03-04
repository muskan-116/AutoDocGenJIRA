from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/headings")
async def get_headings(request: Request, template: str = Query(...)):
    db = request.app.state.db.get_collection("templates")
    
    # Case-insensitive search
    import re
    doc = await db.find_one({"template_name": re.compile(f"^{template.strip()}$", re.IGNORECASE)})

    if not doc:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": f"No data found for template '{template}'"}
        )

    # Build response dynamically based on template type
    template_type = doc.get("type", "").lower()
    response = {
        "status": "success",
        "template_name": doc.get("template_name"),
        "type": template_type,
    }

    if template_type in ["section", "hierarchical"]:
        # Hierarchical / section-based templates (SRS, SprintReport)
        response["structure"] = doc.get("structure") or doc.get("sections") or []
    elif template_type == "table":
        response["project_fields"] = doc.get("project_fields")
        response["table_columns"] = doc.get("table_columns", [])
    elif template_type == "hierarchical":
        response["sections"] = doc.get("sections", [])
    else:
        response["data"] = doc  # fallback, return the raw document

    return response
