# Monorepo phone_call_project — AI/ (Python), BE/ (NestJS), FE/ (React)
#
#   make dev     kéo toàn bộ lên: Docker (Postgres+Redis+ngrok) -> BE -> FE -> AI
#   make stop    tắt hết (chỉ tiến trình của repo này, không đụng cổng của project khác)
#   make check   gọi thử /health các service
#   make setup   chỉ cài dependency + tạo .env, không chạy gì
#
# Mọi target đều idempotent, chạy lại thoải mái.

SHELL := /bin/bash
.DEFAULT_GOAL := help

PY      ?= python3
VENV    := AI/.venv
PIP     := $(VENV)/bin/pip

.PHONY: help dev setup deps env infra infra-stop stop check logs clean

help:
	@echo "make dev      chạy toàn bộ hệ thống (Ctrl+C để dừng)"
	@echo "make stop     dừng Docker + các service do make dev chạy"
	@echo "make check    kiểm tra /health BE, AI, ngrok"
	@echo "make setup    cài dependency + tạo .env từ .env.example"
	@echo "make logs     xem log Docker"
	@echo "make clean    xóa node_modules / .venv (giữ data Postgres)"

# ---------------------------------------------------------------- dev ----

dev: setup infra
	@./scripts/dev.sh

# -------------------------------------------------------------- setup ----

setup: env deps

env: .env AI/.env BE/.env FE/.env

.env AI/.env BE/.env FE/.env:
	@cp $(@D)/.env.example $@ && echo ">> tạo $@ từ .env.example — nhớ điền key thật"

deps: BE/node_modules FE/node_modules $(VENV)/.stamp

BE/node_modules: BE/package-lock.json
	@echo ">> npm install BE"; cd BE && npm install --no-audit --no-fund
	@touch $@

FE/node_modules: FE/package-lock.json
	@echo ">> npm install FE"; cd FE && npm install --no-audit --no-fund
	@touch $@

$(VENV)/.stamp: AI/requirements.txt
	@echo ">> python venv + pip install AI"
	@test -d $(VENV) || $(PY) -m venv $(VENV)
	@$(PIP) install -q --upgrade pip
	@$(PIP) install -q -r AI/requirements.txt
	@touch $@

# -------------------------------------------------------------- infra ----

infra:
	@./scripts/docker-up.sh

infra-stop:
	@docker compose --profile ngrok stop

# --------------------------------------------------------------- stop ----

stop: infra-stop
	@./scripts/stop.sh

# -------------------------------------------------------------- check ----

check:
	@./scripts/check.sh

logs:
	@docker compose --profile ngrok logs -f --tail=50

clean:
	@rm -rf BE/node_modules FE/node_modules $(VENV)
	@echo ">> đã xóa dependency. Data Postgres vẫn còn trong volume docker."
