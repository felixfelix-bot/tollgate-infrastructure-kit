# ngit-tool.mk — Makefile for ngit operations
# Include or run directly from Hermes: make -f ngit-tool.mk <target>
#
# These targets call ngit-tool.sh so no TTY/LLM reasoning needed.
# Hermes just runs `make -f ~/ngit-tool.mk <target> REPO=... BRANCH=...`

# --- Required variables ---
REPO ?= $(PWD)
BRANCH ?= HEAD
NURL ?=

# --- Targets ---

# ngit init — init a repo on nostr git
ngit-init:
	~/scripts/ngit-tool.sh init "$(REPO)" "$(NAME)"

# ngit push — push a branch to ngit
ngit-push:
	~/scripts/ngit-tool.sh push "$(REPO)" "$(BRANCH)"

# ngit sync — sync repo with nostr state
ngit-sync:
	~/scripts/ngit-tool.sh sync "$(REPO)"

# ngit status — show ngit status
ngit-status:
	~/scripts/ngit-tool.sh status "$(REPO)"

# ngit fix — fix ngit configuration
ngit-fix:
	~/scripts/ngit-tool.sh fix "$(REPO)"

# ngit clone — clone from ngit
ngit-clone:
	~/scripts/ngit-tool.sh clone "$(NURL)" "$(DEST)"

# ngit all — init + push + status
ngit-all: ngit-init ngit-push ngit-status

# Quick push: push current branch of current repo
ngit-quick-push:
	~/scripts/ngit-tool.sh push "$(PWD)"
