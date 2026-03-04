# backend/app/graph/nodes/pm_agent.py

import httpx


# --------------------------------------------------
# Resolve board name → board ID
# --------------------------------------------------
async def get_board_id_from_name(
    trello_key: str,
    trello_token: str,
    board_name: str
) -> str:
    if not board_name or board_name == "undefined":
        raise ValueError("Board name is empty or undefined")

    url = "https://api.trello.com/1/members/me/boards"
    params = {
        "key": trello_key,
        "token": trello_token,
        "fields": "id,name"
    }

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(url, params=params)

    if res.status_code != 200:
        raise ValueError(f"Trello API error {res.status_code}: {res.text}")

    for board in res.json():
        if board["name"].strip().lower() == board_name.strip().lower():
            return board["id"]

    raise ValueError(f"No Trello board found with name '{board_name}'")


# --------------------------------------------------
# PM Agent Node
# --------------------------------------------------
async def fetch_pm_data_node(state: dict) -> dict:
    trello_key = state.get("user_trello_key")
    trello_token = state.get("user_trello_token")

    # 🔥 THIS IS THE ROOT FIX
    project_id = state.get("project_id") or state.get("board_id")
    project_name = state.get("project_name")

    if not trello_key:
        raise ValueError("TRELLO_API_KEY missing in workflow state")

    if not trello_token:
        raise ValueError("Trello token missing in workflow state")

    if not project_id and not project_name:
        raise ValueError("Both project_id and project_name are missing")

    # --------------------------------------------------
    # Resolve board ID
    # --------------------------------------------------
    if project_id and len(project_id) == 24:
        board_id = project_id
    elif project_name:
        board_id = await get_board_id_from_name(
            trello_key,
            trello_token,
            project_name
        )
    else:
        raise ValueError("Unable to resolve Trello board")

    # --------------------------------------------------
    # Fetch cards
    # --------------------------------------------------
    url = f"https://api.trello.com/1/boards/{board_id}/cards"
    params = {
        "key": trello_key,
        "token": trello_token,
        "fields": "id,name,desc,idList"
    }

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(url, params=params)

    if res.status_code != 200:
        raise ValueError(f"Trello cards fetch failed: {res.text}")

    state["pm_data"] = {
        "board_id": board_id,
        "cards": res.json()
    }

    return state
