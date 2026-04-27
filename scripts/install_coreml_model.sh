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
APP_MODELS_DIR="${ROOT_DIR}/GreenLight/Models"
MODEL_BASENAME="$(basename "$MODEL_PATH")"
MODEL_EXT=""
if [[ "$MODEL_BASENAME" == *.mlpackage ]]; then
  MODEL_EXT=".mlpackage"
elif [[ "$MODEL_BASENAME" == *.mlmodel ]]; then
  MODEL_EXT=".mlmodel"
fi

if [[ ! -e "$MODEL_PATH" ]]; then
  echo "Model path does not exist: $MODEL_PATH"
  exit 1
fi

mkdir -p "$APP_MODELS_DIR"
DEST_PATH="${APP_MODELS_DIR}/${MODEL_NAME}${MODEL_EXT}"

if [[ -d "$MODEL_PATH" ]]; then
  rm -rf "$DEST_PATH"
  cp -R "$MODEL_PATH" "$DEST_PATH"
else
  cp "$MODEL_PATH" "$DEST_PATH"
fi

echo "Installed model into: $APP_MODELS_DIR"
echo "Installed as: $(basename "$DEST_PATH")"
echo "Next steps:"
echo "1) Open GreenLight.xcodeproj"
echo "2) Ensure the new model is included in app target's Copy Bundle Resources"
echo "3) If needed, update model filename in GreenLight/ViewControllers/ViewControllerDetection.swift"
echo "   Current lookup order: yolo26nTraffic(.mlmodelc/.mlpackage) -> yolo11nTraffic(.mlmodelc/.mlpackage) -> yolov8nTraffic(.mlmodelc/.mlpackage) -> yolov5sTraffic(.mlmodelc/.mlmodel)"
