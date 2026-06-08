from flask import render_template, jsonify, request, redirect, url_for, flash

from spore._engine.model_manager import reset_engine
from spore._utils import model_ls, load_settings, save_settings
from spore._config.settings import (
    PROVIDER_FIELDS,
    PROVIDER_BASE_URLS,
    URL_CONFIGURABLE_PROVIDERS,
)
from spore._routes.utils import generate_blueprint

from spore._logger import logging


settings_blueprint = generate_blueprint('settings')

@settings_blueprint.route('/settings', methods=['GET', 'POST'])
def settings():
    settings = load_settings() or {}
    provider, model = settings.get("provider", None), settings.get("model", None)

    if request.method == "POST":
        try:
            provider = request.form.get("provider")

            existing = load_settings() or {}
            api_keys = dict(existing.get("api_keys") or {})
            submitted_key = (request.form.get("api_key") or "").strip()
            if submitted_key and provider:
                api_keys[provider] = submitted_key

            # Per-provider endpoint URL. Empty submission reverts to the default
            # (we drop the key so the resolver falls back to PROVIDER_BASE_URLS).
            base_urls = dict(existing.get("base_urls") or {})
            submitted_url = (request.form.get("base_url") or "").strip().rstrip("/")
            if provider in URL_CONFIGURABLE_PROVIDERS:
                if submitted_url:
                    base_urls[provider] = submitted_url
                else:
                    base_urls.pop(provider, None)

            new_data = {
                "provider": provider,
                "model": request.form.get("model", settings.get("model")),
                "keep_alive": request.form.get("keep_alive", "5m"),
                "api_keys": api_keys,
                "base_urls": base_urls,
                "options": {
                    "num_predict":       int(request.form.get("num_predict", 256)),
                    "top_k":             int(request.form.get("top_k", 40)),
                    "top_p":             float(request.form.get("top_p", 0.9)),
                    "temperature":       float(request.form.get("temperature", 0.7)),
                    "num_ctx":           int(request.form.get("num_ctx", 2048)),
                    "num_batch":         int(request.form.get("num_batch", 4)),
                    "num_thread":        int(request.form.get("num_thread", 8)),
                    "num_gpu":           int(request.form.get("num_gpu", 0)),
                    "repeat_penalty":    float(request.form.get("repeat_penalty", 1.1)),
                    "use_mmap":          request.form.get("use_mmap") == "true",
                    "use_mlock":         request.form.get("use_mlock") == "false",
                    "frequency_penalty": float(request.form.get("frequency_penalty", 0.0)),
                    "presence_penalty":  float(request.form.get("presence_penalty", 0.0)),
                }
            }

            save_settings(new_data)
            reset_engine()
            flash("Settings updated successfully!", "success")
  
        except Exception as e:
            logging.error(f"Error saving settings: {str(e)}")
            flash("Failed to save settings. Please check the logs for details.", "error")
            return redirect(url_for('endpoints.settings'))
    
    return render_template(
        'pages/settings.html',
        settings=settings,
        provider_fields=PROVIDER_FIELDS,
        provider_base_urls=PROVIDER_BASE_URLS,
        url_providers=URL_CONFIGURABLE_PROVIDERS,
        current_provider=provider,
        current_model=model,
        all_providers=list(PROVIDER_FIELDS.keys()),
    )
    
# ----------------------------------------------------------------------------------------------------
# Helper endpoints

@settings_blueprint.route('/models_list')
def models_list():
    provider = request.args.get("provider")
    if not provider:
        return jsonify({"error": "No provider specified"}), 400

    # Optional ad-hoc URL so the UI can test an endpoint before saving it.
    base_url = (request.args.get("base_url") or "").strip().rstrip("/") or None

    try:
        models = model_ls(provider, base_url)
        return jsonify(models)
    except Exception as e:
        logging.error(f"Failed to fetch models for {provider}: {e}")
        return jsonify({"error": "Could not connect to provider"}), 500
