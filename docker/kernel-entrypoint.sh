#!/bin/sh
set -eu

CONN_FILE="${KERNEL_CONNECTION_FILE:-/tmp/connection.json}"

cat > "$CONN_FILE" <<EOF
{
  "shell_port": ${KERNEL_SHELL_PORT:?},
  "iopub_port": ${KERNEL_IOPUB_PORT:?},
  "stdin_port": ${KERNEL_STDIN_PORT:?},
  "control_port": ${KERNEL_CONTROL_PORT:?},
  "hb_port": ${KERNEL_HB_PORT:?},
  "ip": "0.0.0.0",
  "key": "${KERNEL_KEY:?}",
  "transport": "tcp",
  "signature_scheme": "hmac-sha256",
  "kernel_name": "python3"
}
EOF

exec python -m ipykernel_launcher -f "$CONN_FILE"
