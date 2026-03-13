from app.graph.document_graph import workflow, WorkflowState
from app.services.cleaner import clean_generated_doc
from datetime import datetime
import re
import os


async def execute_jira_workflow(user_id: str, project_key: str, data: dict = None, db=None):
    """
    Jira ke liye alag workflow — Trello token ki zaroorat nahi.
    """
    if db is None:
        raise RuntimeError("Database instance not provided")

    docs_collection = db["generated_docs"]

    template_name = str(data.get("template", "")).strip()
    if not template_name:
        return {"status": "error", "message": "Missing template name"}

    jira_data    = data.get("jira_data", {})
    project_name = jira_data.get("summary", {}).get("project_name", project_key)

    # -------------------- Prepare WorkflowState --------------------
    input_state = WorkflowState(
        project_id=project_key,
        project_name=project_name,
        user_trello_key="",        # Jira mein nahi chahiye
        user_trello_token="",      # Jira mein nahi chahiye
        pm_data=jira_data,         # ✅ Jira structured data yahan
        uploaded_pdf_bytes=b"",
        pdf_headings=[],
        selected_headings=[],
        generated_docs=""
    )

    # -------------------- Run AI Workflow --------------------
    result       = await workflow.ainvoke(input_state)
    raw_doc      = result.get("generated_docs", "")
    formatted_doc = clean_generated_doc(str(raw_doc), project_name)

    # -------------------- Merge with previous version --------------------
    latest_entry = await docs_collection.find_one(
        {
            "user_id": user_id,
            "project_id": project_key,
            "template_name": template_name,
            "source": "jira"
        },
        sort=[("version", -1)]
    )

    if latest_entry:
        existing_doc      = latest_entry.get("generated_docs", "")
        existing_headings = set(re.findall(r'##\s*(.+)', existing_doc, flags=re.IGNORECASE))
        new_sections      = re.findall(r'(##\s*.+?)(?=\n##|\Z)', formatted_doc, flags=re.DOTALL)

        content_to_add = []
        for section in new_sections:
            match = re.match(r'##\s*(.+)', section)
            if match and match.group(1).strip() not in existing_headings:
                content_to_add.append(section.strip())

        if content_to_add:
            formatted_doc = existing_doc.strip() + "\n\n---\n" + "\n\n".join(content_to_add)
        else:
            formatted_doc = existing_doc

    if not formatted_doc.strip():
        formatted_doc = "No content generated."

    # -------------------- Versioning --------------------
    version_count = await docs_collection.count_documents({
        "user_id": user_id,
        "project_id": project_key,
        "template_name": template_name,
        "source": "jira"
    })
    version = version_count + 1

    # -------------------- Save --------------------
    await docs_collection.insert_one({
        "user_id":       user_id,
        "project_id":    project_key,
        "project_key":   project_key,
        "template_name": template_name,
        "version":       version,
        "generated_docs": formatted_doc,
        "board_name":    project_name,
        "source":        "jira",          # ✅ Trello docs se alag identify hoga
        "created_at":    datetime.utcnow()
    })

    return {
        "status":        "success",
        "template_name": template_name,
        "version":       version,
        "generated_docs": formatted_doc
    }
