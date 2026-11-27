# Bakes the config and the masking hook into the image so the stack does not depend on host file sharing.
# Build from the repo root. The hook files sit flat next to the config, where LiteLLM imports them as `mask_hook`
# (the image already has its own /app/gateway package, so ours must not be copied there).
FROM ghcr.io/berriai/litellm:main-stable
COPY gateway/litellm.config.yaml /app/config.yaml
COPY gateway/mask_hook.py gateway/pii.py /app/
