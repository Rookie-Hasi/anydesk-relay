import os
import json
import random

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def generate_device_id():
    # Generates a standard 9-digit ID formatted like AnyDesk: e.g. 849 203 118
    return "".join(str(random.randint(0, 9)) for _ in range(9))

def format_id(raw_id):
    raw = str(raw_id).replace(" ", "").strip()
    if len(raw) == 9:
        return f"{raw[:3]} {raw[3:6]} {raw[6:]}"
    return raw

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                if "id" in data and "pin" in data:
                    return data
        except Exception:
            pass

    # Default initial configuration
    new_config = {
        "id": generate_device_id(),
        "pin": "1234",
        "server_url": "ws://localhost:8765",
        "quality": 60,
        "fps_limit": 30
    }
    save_config(new_config)
    return new_config

def save_config(config_dict):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config_dict, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")
