#!/bin/bash
cd "$(dirname "$0")"
export SECRET_KEY="$(cat .secret_key)"
export PORT=8077
exec python run.py
