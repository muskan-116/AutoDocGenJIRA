def build_trello_message(action: dict) -> str:
    action_type = action.get("type")
    data = action.get("data", {})
    card = data.get("card", {})
    card_name = card.get("name", "a card")

    if action_type == "createCard":
        return f"New card '{card_name}' was created."

    if action_type == "updateCard":
        list_before = data.get("listBefore", {}).get("name")
        list_after = data.get("listAfter", {}).get("name")

        if list_before and list_after:
            return f"Card '{card_name}' was moved from '{list_before}' to '{list_after}'."

        return f"Card '{card_name}' was updated."

    if action_type == "commentCard":
        return f"A comment was added to '{card_name}'."

    return "Changes were made to your Trello board."
