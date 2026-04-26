#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <model_path (.mlpackage|.mlmodel)> [model_name_without_ext]"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_PATH="$1"
MODEL_NAME="${2:-$(basename "$MODEL_PATH")}" 
MODEL_NAME="${MODEL_NAME%.mlpackage}"
MODEL_NAME="${MODEL_NAME%.mlmodel}"
APP_MODELS_DIR="${ROOT_DIR}/DriverAssistant/Models"

if [[ ! -e "$MODEL_PATH" ]]; then
  echo "Model path does not exist: $MODEL_PATH"
  exit 1
fi

mkdir -p "$APP_MODELS_DIR"

if [[ -d "$MODEL_PATH" ]]; then
  cp -R "$MODEL_PATH" "$APP_MODELS_DIR/"
else
  cp "$MODEL_PATH" "$APP_MODELS_DIR/"
fi

echo "Installed model into: $APP_MODELS_DIR"
echo "Next steps:"
echo "1) Open DriverAssistant.xcodeproj"
echo "2) Ensure the new model is included in app target's Copy Bundle Resources"
echo "3) If needed, update model filename in DriverAssistant/ViewControllers/ViewControllerDetection.swift"
echo "   Current lookup expects: yolov5sTraffic.mlmodelc"
