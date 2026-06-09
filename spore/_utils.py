import requests

from spore._logger import logging

from flask import session, Response
from openpyxl import Workbook
from io import StringIO, BytesIO
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import load_dotenv

import os
import ast
import csv
from uuid_extensions import uuid7
import json
import dill

load_dotenv()

def _get_cipher():
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise ValueError("ENCRYPTION_KEY not set in environment")
    return Fernet(key.encode())

def encrypt_creds(creds):
    return _get_cipher().encrypt(json.dumps(creds).encode()).decode()

def decrypt_creds(encrypted_creds):
    try:
        cipher = _get_cipher()
        decrypted_bytes = cipher.decrypt(encrypted_creds.encode())
        decrypted_str = decrypted_bytes.decode()
        try:
            return json.loads(decrypted_str)
        except json.JSONDecodeError:
            # Legacy sessions stored via str(dict) + ast.literal_eval
            return ast.literal_eval(decrypted_str)
    except Exception as e:
        logging.error(f"Decryption failed specifically at: {repr(e)}")
        raise e
    
def generate_id():
    """
    Generate a unique identifier.
    
    Returns:
        str: A unique identifier as a string.
    """
    return uuid7().hex

def validate_query(query: str) -> bool:
    '''
    Validate if the provided query is a non-empty string.
    
    Args:
        query (str): The query string to validate.
    
    Returns:
        bool: True if the query is a non-empty string, False otherwise.
    '''
    return isinstance(query, str) and len(query.strip()) > 0

def get_connection_by_id(conn_id):
    connections = session.get("connections", [])
    return next((conn for conn in connections if str(conn["id"]) == str(conn_id)), None)


def downloadable_csv(raw_data):
    '''
    This function is used to create a downloadable csv file, this is done
    via data streaming to ensure that if the user wants to download a large
    amount of data, it doesn't overflow their ram and crash the system.
    '''
    def generator():
        csv_buffer = StringIO()
        writer = csv.writer(csv_buffer)

        for row in raw_data:
            if isinstance(row, tuple):
                row = list(row)

            writer.writerow(row)
            yield csv_buffer.getvalue()
            csv_buffer.seek(0)
            csv_buffer.truncate(0)
                
    return Response(
        generator(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=data.csv"}
    )

def downloadable_excel(raw_data):
    '''
    This function is used to create a downloadable excel file for the frontend
    '''
    excel_buffer = BytesIO()
    wb = Workbook(write_only=True)
    ws = wb.create_sheet()

    for row in raw_data:
        if isinstance(row, tuple):
            row = list(row)
        ws.append(row)

    wb.save(excel_buffer)
    excel_buffer.seek(0)

    return Response(
        excel_buffer.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment;filename=data.xlsx"}
    )

def downloadable_json(raw_data):
    '''
    This function is used to create a downloadable json file for the frontend
    '''
    data = []

    for row in raw_data:
        if isinstance(row,tuple):
            row = list(row)
        data.append(row)

    headers = data[0]
    rows = data[1:]

    json_data = {
        'headers': headers,
        'rows': rows
    }

    data = json.dumps(json_data)
            
    return Response(
        data,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment;filename=data.json"}
    )

def SETTINGS_FILE():
    """LLM runtime settings JSON (provider, model, options)."""
    repo_root = Path(__file__).parents[1]
    primary = repo_root / "spore" / "_config" / "settings.json"
    legacy = repo_root / "config" / "settings.json"
    if primary.exists():
        return primary
    return legacy

def load_settings():
    logging.info("inside load_settings()")
    if os.path.exists(SETTINGS_FILE()):
        with open(SETTINGS_FILE(), "r") as settings:
            logging.info("loaded settings")
            return json.load(settings)
    return {}

def save_settings(data):
    settings_path = SETTINGS_FILE()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w") as new_settings:
        json.dump(data, new_settings, indent=2)


def merge_settings_section(section: str, patch: dict) -> dict:
    """Merge ``patch`` into ``settings.json`` under ``section``, preserving other keys."""
    data = load_settings() or {}
    current = dict(data.get(section) or {})
    current.update(patch)
    data[section] = current
    save_settings(data)
    return data


def _parse_mem_limit_mb(mem_limit) -> int:
    """Convert Docker-style mem limit (e.g. ``1g``, ``512m``) to megabytes."""
    if isinstance(mem_limit, (int, float)):
        return int(mem_limit)
    raw = str(mem_limit).strip().lower()
    if raw.endswith("g"):
        return int(float(raw[:-1]) * 1024)
    if raw.endswith("m"):
        return int(float(raw[:-1]))
    if raw.endswith("k"):
        return max(1, int(float(raw[:-1]) / 1024))
    return int(float(raw))


def _format_mem_limit_mb(mb: int) -> str:
    return f"{int(mb)}m"


DEFAULT_KERNEL_STARTUP_CODE = """try:
    import sys
    from IPython.core.display import display

    def custom_displayhook(value):
        if value is None:
            return
        display(value)

    sys.displayhook = custom_displayhook

    import plotly.io as pio
    pio.renderers.default = "plotly_mimetype"
except Exception:
    pass
"""


def kernel_runtime(settings_data: dict | None = None) -> dict:
    """Effective kernel config: settings.json overrides env defaults."""
    from spore._config.settings import settings as env

    data = settings_data if settings_data is not None else (load_settings() or {})
    kernel = data.get("kernel") or {}
    python_version = kernel.get("python_version") or env.KERNEL_PYTHON_VERSION
    packages = kernel.get("packages") or []
    if not isinstance(packages, list):
        packages = []
    return {
        "startup_code": kernel.get("startup_code", DEFAULT_KERNEL_STARTUP_CODE),
        "packages": packages,
        "python_version": python_version,
        "image": f"spore-kernel:{python_version}",
        "kernel_spec_name": f"python{python_version.replace('.', '')}",
    }


def security_runtime(settings_data: dict | None = None) -> dict:
    """Effective sandbox limits: settings.json overrides env defaults."""
    from spore._config.settings import settings as env

    data = settings_data if settings_data is not None else (load_settings() or {})
    security = data.get("security") or {}
    default_mb = _parse_mem_limit_mb(env.KERNEL_MEM_LIMIT)
    mem_limit_mb = int(security.get("mem_limit_mb", default_mb))
    pids_limit = int(security.get("pids_limit", env.KERNEL_PIDS_LIMIT))
    exec_timeout = int(security.get("exec_timeout", 30))
    return {
        "mem_limit_mb": mem_limit_mb,
        "mem_limit": _format_mem_limit_mb(mem_limit_mb),
        "pids_limit": pids_limit,
        "exec_timeout": exec_timeout,
    }


def data_runtime(settings_data: dict | None = None) -> dict:
    """Effective data/cache config: settings.json overrides env defaults."""
    from spore._config.settings import settings as env

    data = settings_data if settings_data is not None else (load_settings() or {})
    data_cfg = data.get("data") or {}
    return {
        "batch_row_size": int(data_cfg.get("batch_row_size", 10_000)),
        "connect_timeout": int(data_cfg.get("connect_timeout", 5)),
        "data_dir": data_cfg.get("data_dir") or env.SPORE_DATA_DIR,
    }


def repo_root() -> Path:
    return Path(__file__).parents[1]


def provider_base_url(provider, settings=None):
    """Resolve the effective base URL for an LLM provider.

    Precedence: settings.json ``base_urls[provider]`` > env-derived default
    (``PROVIDER_BASE_URLS``). Empty/unset falls back to the default so behavior
    stays the same when the user has not customized anything.
    """
    from spore._config.settings import PROVIDER_BASE_URLS

    prov = (provider or "").lower().strip()
    settings = settings if settings is not None else (load_settings() or {})
    configured = (settings.get("base_urls") or {}).get(prov)
    if configured and str(configured).strip():
        return str(configured).strip().rstrip("/")
    default = PROVIDER_BASE_URLS.get(prov) or ""
    return default.rstrip("/")

def is_running_in_docker():
    """Check if the app is running inside a Docker container."""
    path = "/proc/self/cgroup"
    if os.path.exists("/.dockerenv"):
        return True
    if os.path.isfile(path):
        with open(path) as f:
            return any("docker" in line for line in f)
    return False

def model_ls(provider, base_url=None):
    if provider == "ollama":
        return ollama_model_ls(base_url)
    elif provider == "lmstudio":
        return lmstudio_model_ls(base_url)
    else:
        return []
    
def ollama_model_ls(base_url=None):
    OLLAMA_BASE = (base_url or provider_base_url("ollama")).rstrip("/")
    OLLAMA_TAGS = (f'{OLLAMA_BASE}/api/tags')
    tag_data = requests.get(OLLAMA_TAGS).json()['models']

    models = []
    for row in tag_data:
        model = {
            'model':row.get('model'),
            'model_size':row.get('size'),
            'paramater_size': row['details'].get('parameter_size')
        }
        models.append(model)

    return models

def lmstudio_model_ls(base_url=None):
    LMSTUDIO_BASE = (base_url or provider_base_url("lmstudio")).rstrip("/")
    LMSTUDIO_TAGS = (f'{LMSTUDIO_BASE}/api/v1/models')

    tag_data = requests.get(LMSTUDIO_TAGS).json()

    models = []
    print(tag_data)
    for unit in tag_data.get('models'):
        if unit.get('type') == 'llm':
            model = {
                'model':unit.get('key'),
                'model_size': int(unit.get('size_bytes')),
                'paramater_size': unit.get('params_string')
            }
            models.append(model)
    return models

_MODEL_CONTEXT_CACHE: dict[str, int | None] = {}


def clear_model_context_cache() -> None:
    """Clear cached provider model context probes (call on engine reset)."""
    _MODEL_CONTEXT_CACHE.clear()


def ollama_model_context(model: str) -> int | None:
    """Return Ollama model max context length via /api/show, or None on failure."""
    base = provider_base_url("ollama")
    if not base or not model:
        return None
    try:
        resp = requests.post(
            f"{base.rstrip('/')}/api/show",
            json={"model": model},
            timeout=5,
        )
        resp.raise_for_status()
        model_info = resp.json().get("model_info") or {}
        for key, value in model_info.items():
            if key.endswith(".context_length") and value is not None:
                return int(value)
    except Exception as exc:
        logging.warning("ollama_model_context failed for %s: %s", model, exc)
    return None


def lmstudio_model_context(model: str) -> int | None:
    """Return LM Studio model max context length, or None on failure."""
    base = provider_base_url("lmstudio")
    if not base or not model:
        return None
    try:
        resp = requests.get(f"{base.rstrip('/')}/api/v1/models", timeout=5)
        resp.raise_for_status()
        for unit in (resp.json().get("models") or []):
            if unit.get("type") != "llm":
                continue
            if unit.get("key") != model:
                continue
            for field in ("max_context_length", "loaded_context_length"):
                val = unit.get(field)
                if val is not None:
                    return int(val)
    except Exception as exc:
        logging.warning("lmstudio_model_context failed for %s: %s", model, exc)
    return None


def model_max_context(provider: str, model: str) -> int | None:
    """Probe provider for model max context window; cached per provider:model."""
    prov = (provider or "").lower().strip()
    name = (model or "").strip()
    if not prov or not name:
        return None
    cache_key = f"{prov}:{name}"
    if cache_key in _MODEL_CONTEXT_CACHE:
        return _MODEL_CONTEXT_CACHE[cache_key]
    try:
        if prov == "ollama":
            result = ollama_model_context(name)
        elif prov == "lmstudio":
            result = lmstudio_model_context(name)
        else:
            result = None
    except Exception as exc:
        logging.warning("model_max_context failed for %s/%s: %s", prov, name, exc)
        result = None
    _MODEL_CONTEXT_CACHE[cache_key] = result
    return result


def context_limit_info(settings: dict | None = None) -> dict[str, int | bool | None]:
    """
    Effective context window for the UI indicator.

    effective = min(configured num_ctx, model max) when model max is known.
    show is True only for local providers (ollama, lmstudio).
    """
    settings = settings if settings is not None else (load_settings() or {})
    provider = (settings.get("provider") or "").lower()
    model = settings.get("model") or ""
    configured = int((settings.get("options") or {}).get("num_ctx", 2048))
    model_max = model_max_context(provider, model)
    effective = min(configured, model_max) if model_max else configured
    clamped = bool(model_max and configured > model_max)
    show = provider in {"ollama", "lmstudio"}
    return {
        "configured": configured,
        "model_max": model_max,
        "effective": effective,
        "clamped": clamped,
        "show": show,
    }


def file_size_fmt(size):
    if size < 1024:
        return f"{size} B"
    elif size < 1024**2:
        return f"{size / 1024:.1f} KB"
    elif size < 1024**3:
        return f"{size / 1024**2:.1f} MB"
    else:
        return f"{size / 1024**3:.2f} GB"