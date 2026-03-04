import requests

def get_user_boards(trello_key, trello_token):
    url = "https://api.trello.com/1/members/me/boards"
    params = {"key": trello_key, "token": trello_token, "fields": "name,id"}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching user boards: {e}")
        return []

def get_pm_data(board_id, trello_key, trello_token):
    base_url = "https://api.trello.com/1"
    params = {"key": trello_key, "token": trello_token}

    try:
        # Fetch lists for the board
        lists_resp = requests.get(f"{base_url}/boards/{board_id}/lists", params=params)
        if lists_resp.status_code != 200:
            print(f"❌ Trello API Error {lists_resp.status_code}: {lists_resp.text}")
            return {}
        lists = lists_resp.json()

        board_data = {}
        for lst in lists:
            cards_resp = requests.get(f"{base_url}/lists/{lst['id']}/cards", params=params)
            if cards_resp.status_code != 200:
                print(f"⚠️ Skipping list {lst['name']} - API error {cards_resp.status_code}: {cards_resp.text}")
                continue
            cards = cards_resp.json()
            board_data[lst["name"]] = [
                {"id": c["id"], "name": c["name"], "desc": c["desc"], "url": c["shortUrl"]}
                for c in cards
            ]

        return board_data

    except requests.exceptions.RequestException as e:
        print(f"🚨 Request failed: {e}")
        return {}
    except ValueError as e:
        print(f"🚨 JSON decode failed: {e}")
        return {}
