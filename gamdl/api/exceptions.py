import json
from ..utils import GamdlError


class ApiError(GamdlError):
    def __init__(self, message: str, status_code: int):
        clean_msg = message
        try:
            parsed = json.loads(message)
            if isinstance(parsed, dict):
                if "errors" in parsed and isinstance(parsed["errors"], list) and parsed["errors"]:
                    clean_msg = parsed["errors"][0].get("detail") or parsed["errors"][0].get("title") or message
                elif "detail" in parsed:
                    clean_msg = parsed["detail"]
                elif "message" in parsed:
                    clean_msg = parsed["message"]
        except Exception:
            pass

        if clean_msg and len(clean_msg) > 300:
            clean_msg = clean_msg[:300] + "..."

        super().__init__(f"API Error {status_code}: {clean_msg}")
        self.status_code = status_code
