UV_VERSION ?= 0.12.3
UV ?= uvx --from uv==$(UV_VERSION) uv

.PHONY: help sync run test self-test build-mac

help:
	@echo "make sync       依存関係をインストール"
	@echo "make run        アプリを起動"
	@echo "make test       テストを実行"
	@echo "make self-test  HEICからJPEGへの変換を確認"
	@echo "make build-mac  Mac用アプリを作成"

sync:
	$(UV) sync --frozen --all-groups

run:
	$(UV) run --frozen python app.py

test:
	$(UV) run --frozen pytest -q

self-test:
	$(UV) run --frozen python app.py --self-test

build-mac: sync
	./build-mac.sh
