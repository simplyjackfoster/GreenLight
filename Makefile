SHELL := /bin/bash

ROOT_DIR := $(abspath .)
DATASETS_DIR := $(ROOT_DIR)/export/datasets
MODELS_DIR := $(ROOT_DIR)/export/models
CHECKPOINTS_DIR := $(MODELS_DIR)/checkpoints
COREML_EXPORT_DIR := $(MODELS_DIR)/coreml
APP_MODELS_DIR := $(ROOT_DIR)/DriverAssistant/Models
VENV_DIR := $(ROOT_DIR)/.venv-dataset

PYTHON := $(if $(wildcard $(VENV_DIR)/bin/python3),$(VENV_DIR)/bin/python3,python3)

.PHONY: help py-deps py-compile dataset-smoke dataset-crops dataset-merge pipeline-check install-coreml clean-datasets

help:
	@echo "Targets:"
	@echo "  py-deps        Install python deps for dataset tooling"
	@echo "  py-compile     Compile-check CocoTraffic scripts"
	@echo "  dataset-smoke  Run tiny synthetic smoke pipeline"
	@echo "  dataset-crops  Generate crop dataset from COCO JSON"
	@echo "  dataset-merge  Merge two crop datasets"
	@echo "  pipeline-check Validate merged dataset"
	@echo "  install-coreml Copy exported CoreML model into DriverAssistant/Models"
	@echo "  clean-datasets Remove generated dataset artifacts"

py-deps:
	python3 -m venv "$(VENV_DIR)"
	"$(VENV_DIR)/bin/python3" -m pip install --upgrade pip
	"$(VENV_DIR)/bin/python3" -m pip install pillow pandas tqdm

py-compile:
	$(PYTHON) -m py_compile cocoTraffic/api/make_datasets.py
	$(PYTHON) -m py_compile cocoTraffic/api/make_yolo_labels.py
	$(PYTHON) -m py_compile cocoTraffic/tools/makesense/append_LISA_to_coco_splits.py
	$(PYTHON) -m py_compile cocoTraffic/tools/s2tld_extractor.py
	$(PYTHON) -m py_compile cocoTraffic/tools/merge_datasets.py
	$(PYTHON) -m py_compile cocoTraffic/tools/pipeline_check.py

dataset-smoke:
	PYTHON="$(PYTHON)" bash cocoTraffic/tools/ci/smoke_pipeline.sh

# Example usage:
# make dataset-crops ANNOTATIONS=export/datasets/raw/annotations INPUT_IMAGES=export/datasets/raw/images DATASET=val_new_images OUTPUT=export/datasets/crops/coco
ANNOTATIONS ?= $(DATASETS_DIR)/raw/annotations
INPUT_IMAGES ?= $(DATASETS_DIR)/raw/images
DATASET ?= val_new_images
OUTPUT ?= $(DATASETS_DIR)/crops/coco
CLASSES ?= red green yellow off na

dataset-crops:
	mkdir -p "$(OUTPUT)"
	$(PYTHON) cocoTraffic/api/make_yolo_labels.py \
		--annotations "$(ANNOTATIONS)" \
		--input "$(INPUT_IMAGES)" \
		--output "$(OUTPUT)" \
		--dataset-name "$(DATASET)" \
		--output-format crops \
		--classes $(CLASSES) \
		--min-box-size 400 \
		--crop-size 64 \
		--padding 0.15 \
		--split 0.85 \
		--verbose

# Example usage:
# make dataset-merge DATASET_A=export/datasets/crops/coco DATASET_B=export/datasets/crops/s2tld MERGED=export/datasets/merged/main
DATASET_A ?= $(DATASETS_DIR)/crops/coco
DATASET_B ?= $(DATASETS_DIR)/crops/s2tld
MERGED ?= $(DATASETS_DIR)/merged/main

dataset-merge:
	mkdir -p "$(MERGED)"
	$(PYTHON) cocoTraffic/tools/merge_datasets.py \
		--input "$(DATASET_A)" "$(DATASET_B)" \
		--output "$(MERGED)" \
		--verbose

# Example usage:
# make pipeline-check MERGED=export/datasets/merged/main
pipeline-check:
	$(PYTHON) cocoTraffic/tools/pipeline_check.py \
		--input "$(MERGED)" \
		--sample-per-class 10 \
		--verbose

# Example usage:
# make install-coreml MODEL_PATH=export/models/coreml/yolov8nTraffic.mlpackage
MODEL_PATH ?= $(COREML_EXPORT_DIR)/yolov8nTraffic.mlpackage
MODEL_NAME ?= yolov8nTraffic

install-coreml:
	bash scripts/install_coreml_model.sh "$(MODEL_PATH)" "$(MODEL_NAME)"

clean-datasets:
	rm -rf "$(DATASETS_DIR)/ci-smoke" "$(DATASETS_DIR)/crops" "$(DATASETS_DIR)/merged"
