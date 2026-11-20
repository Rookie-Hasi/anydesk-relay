import os
import sys
import json
import random

def get_config_dir():
    # Use permanent system APPDATA directory so the ID NEVER changes even when compiled to .exe
    appdata = os.environ.get("APPDATA")
    if appdata:
        folder = os.path.join(appdata, "AnyDeskClone")
    else:
        folder = os.path.join(os.path.expanduser("~"), ".anydeskclone")
    os.makedirs(folder, exist_ok=True)
    return folder

CONFIG_FILE = os.path.join(get_config_dir(), "config.json")

def generate_device_id():
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
        "server_url": "wss://anydesk-relay-production.up.railway.app",
        "quality": 55,
        "fps_limit": 25,
        "scale": 0.75
    }
    save_config(new_config)
    return new_config

def save_config(config_dict):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config_dict, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")
