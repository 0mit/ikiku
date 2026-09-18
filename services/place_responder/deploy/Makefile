# Part of place_responder. Licensed under AGPL-3.0.
#   make test     the Go tests (parity with search_suggest's Python ranking included)
#   make build    a static linux/amd64 binary, deploy/place_responder
#   make image    ikiku/place-responder:<git describe>, FROM scratch
#   make save     that image as deploy/place-responder-<version>.tar.gz, ready to ship
VERSION := $(shell git describe --always --dirty 2>/dev/null || echo dev)
IMAGE   := ikiku/place-responder:$(VERSION)

test:
	cd .. && go vet ./... && go test ./...

build:
	cd .. && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o deploy/place_responder .

image: build
	docker build -t $(IMAGE) .
	@echo $(IMAGE)

save: image
	docker save $(IMAGE) | gzip > place-responder-$(VERSION).tar.gz
	@ls -la place-responder-$(VERSION).tar.gz

.PHONY: test build image save
