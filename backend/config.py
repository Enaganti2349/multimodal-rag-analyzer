import os
import json

class Config:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    DATA_DIR = "data"
    UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
    IMAGES_DIR = os.path.join(DATA_DIR, "extracted_images")
    CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

    @classmethod
    def setup_dirs(cls):
        os.makedirs(cls.DATA_DIR, exist_ok=True)
        os.makedirs(cls.UPLOADS_DIR, exist_ok=True)
        os.makedirs(cls.IMAGES_DIR, exist_ok=True)
        # Load API key from persistent config if available
        if os.path.exists(cls.CONFIG_FILE):
            try:
                with open(cls.CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    cls.GEMINI_API_KEY = data.get("GEMINI_API_KEY", cls.GEMINI_API_KEY)
            except Exception as e:
                print(f"Error loading config.json: {e}")

    @classmethod
    def save_api_key(cls, api_key: str):
        cls.GEMINI_API_KEY = api_key
        try:
            with open(cls.CONFIG_FILE, "w") as f:
                json.dump({"GEMINI_API_KEY": api_key}, f)
        except Exception as e:
            print(f"Error saving config.json: {e}")
