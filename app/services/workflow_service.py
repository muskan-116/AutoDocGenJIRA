from app.graph.document_graph import workflow, WorkflowState
from app.models.user_token_model import get_user_token
from app.services.trello_service import get_board_name
from app.services.cleaner import clean_generated_doc
from datetime import datetime
import re
import os


async def execute_workflow(user_id: str, project_id: str, data: dict = None, db=None):
    if db is None:
        raise RuntimeError("Database instance not provided")

    docs_collection = db["generated_docs"]

    # -------------------- Fetch Trello token --------------------
    token = await get_user_token(user_id, db)
    if not token:
        return {
            "status": "error",
            "message": "User not connected to Trello"
        }

    pdf_headings = data.get("pdf_headings", []) if data else []
    selected_headings = data.get("selected_headings", []) if data else []
    template_name = str(data.get("template", "")).strip()

    if not template_name:
        return {
            "status": "error",
            "message": "Missing template name"
        }

    # -------------------- Get Board Name --------------------
    board_name = await get_board_name(user_id, project_id, db)

    # -------------------- Prepare WorkflowState --------------------
    input_state = WorkflowState(
        project_id=project_id,
        project_name=board_name,
        user_trello_key=os.getenv("TRELLO_API_KEY"),
        user_trello_token=token,
        pm_data={},
        uploaded_pdf_bytes=b"",
        pdf_headings=pdf_headings,
        selected_headings=selected_headings,
        generated_docs=""
    )

    # -------------------- Run AI Workflow --------------------
    result = await workflow.ainvoke(input_state)
    raw_doc = result.get("generated_docs", "")

    formatted_doc = clean_generated_doc(str(raw_doc), board_name)

    # -------------------- Merge with previous version (if exists) --------------------
    latest_entry = await docs_collection.find_one(
        {
            "user_id": user_id,
            "project_id": project_id,
            "template_name": template_name
        },
        sort=[("version", -1)]
    )

    if latest_entry:
        existing_doc = latest_entry.get("generated_docs", "")
        existing_headings = set(
            re.findall(r'##\s*(.+)', existing_doc, flags=re.IGNORECASE)
        )

        new_sections = re.findall(
            r'(##\s*.+?)(?=\n##|\Z)',
            formatted_doc,
            flags=re.DOTALL
        )

        content_to_add = []

        for section in new_sections:
            match = re.match(r'##\s*(.+)', section)
            if match:
                heading = match.group(1).strip()
                if heading not in existing_headings:
                    content_to_add.append(section.strip())

        if content_to_add:
            formatted_doc = (
                existing_doc.strip()
                + "\n\n---\n"
                + "\n\n".join(content_to_add)
            )
        else:
            formatted_doc = existing_doc

    # -------------------- Safety fallback --------------------
    if not formatted_doc.strip():
        formatted_doc = "No content generated."

    # -------------------- Versioning --------------------
    version_count = await docs_collection.count_documents({
        "user_id": user_id,
        "project_id": project_id,
        "template_name": template_name
    })

    version = version_count + 1

    # -------------------- Save as NEW VERSION --------------------
    await docs_collection.insert_one({
        "user_id": user_id,
        "project_id": project_id,
        "template_name": template_name,
        "version": version,
        "generated_docs": formatted_doc,
        "board_name": board_name,
        "created_at": datetime.utcnow()
    })

    return {
        "status": "success",
        "template_name": template_name,
        "version": version,
        "generated_docs": formatted_doc
    }
