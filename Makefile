# ── Infrastructure targets ──────────────────────────────────────
.PHONY: deploy test teardown deploy-mint remove-mint lint check

deploy:
	@bash scripts/deploy.sh

test:
	@bash scripts/test.sh

teardown:
	@bash scripts/teardown.sh

deploy-mint:
	@bash scripts/deploy-mint.sh $(NPUB)

remove-mint:
	@bash scripts/remove-mint.sh $(MINT_ID)

lint:
	@echo "Linting Ansible playbooks..."
	@ansible-lint ansible/playbooks/ ansible/roles/

check:
	@echo "Syntax check..."
	@ansible-playbook -i ansible/inventory/hosts.yml ansible/playbooks/setup-all.yml --syntax-check

# ── nak (Nostr Army Knife) targets ─────────────────────────────
# Nak is the nostr army knife CLI (v0.18.6) at ~/.local/bin/nak.
# Source: https://github.com/fiatjaf/nak
# These targets wrap common nak operations for the project.

NAK       := $(shell command -v nak 2>/dev/null || echo ~/.local/bin/nak)
NAK_KEY   := $(shell [ -f ~/nostr-glasses/secrets/.env ] && grep NOSTR_SECRET_KEY ~/nostr-glasses/secrets/.env | cut -d= -f2 || echo "")
NAK_PUBKEY:= $(shell [ -n "$(NAK_KEY)" ] && $(NAK) key public "$(NAK_KEY)" 2>/dev/null || echo "")
NAK_RELAYS:= wss://relay.damus.io wss://nos.lol

.PHONY: nak-check nak-pubkey nak-board-publish nak-board-sync \
        nak-board-inbound nak-pending nak-events nak-help

nak-check:       ## Check if nak is installed and accessible
	@if command -v nak >/dev/null 2>&1; then \
		echo "✓ nak found: $$(which nak) $$(nak --version 2>&1 | head -1)"; \
	elif [ -x ~/.local/bin/nak ]; then \
		echo "✓ nak found: ~/.local/bin/nak $$(~/.local/bin/nak --version 2>&1 | head -1)"; \
	else \
		echo "✗ nak NOT found. Install from: https://github.com/fiatjaf/nak"; \
		echo "  Quick install: curl -sSL https://raw.githubusercontent.com/fiatjaf/nak/master/install.sh | bash"; \
	fi

nak-pubkey:      ## Show your Nostr pubkey from the configured .env
	@if [ -n "$(NAK_PUBKEY)" ]; then \
		echo "npub: $$($(NAK) encode npub $(NAK_PUBKEY) 2>/dev/null || echo $(NAK_PUBKEY))"; \
		echo "hex:  $(NAK_PUBKEY)"; \
	else \
		echo "No Nostr key configured. Set NOSTR_SECRET_KEY in ~/nostr-glasses/secrets/.env"; \
	fi

nak-board-publish: ## Publish (or refresh) the kanbanstr board event (kind 30301)
	@if [ -z "$(NAK_KEY)" ]; then \
		echo "✗ NOSTR_SECRET_KEY not set. Source ~/nostr-glasses/secrets/.env first."; exit 1; fi
	$(NAK) event --sec "$(NAK_KEY)" -k 30301 \
		-d "net4sats-human-gate" \
		-t "title=net4sats Human Gate" \
		-t "description=Human-approval queue for net4sats MVP tasks. Workers block, humans review." \
		-t "col=Backlog" -t "col=In Progress" -t "col=Human Review" -t "col=Blocked" -t "col=Done" \
		-t "p=$(NAK_PUBKEY)" \
		$(NAK_RELAYS)

nak-board-sync:  ## Sync pending human-gate items to Nostr (kind 30302 cards)
	@bash ~/scripts/nostr-kanban-sync.sh

nak-board-inbound: ## Import external Nostr cards into local human-gate board
	@bash ~/scripts/nostr-kanban-inbound-sync.sh

nak-pending:     ## Query pending human-gate items from Nostr relay
	@if [ -z "$(NAK_PUBKEY)" ]; then \
		echo "No pubkey available. Configure ~/nostr-glasses/secrets/.env"; exit 1; fi
	@echo "Querying kind 30302 events on board net4sats-human-gate..."
	$(NAK) req -k 30302 -t "a=30301:$(NAK_PUBKEY):net4sats-human-gate" $(NAK_RELAYS) 2>/dev/null | \
		python3 -c "import sys,json; evs=[json.loads(l) for l in sys.stdin if l.strip()]; [print(f'  [{e.get(\"pubkey\",\"?\")[:12]}][{\"| \".join(t[1] for t in e.get(\"tags\",[]) if t[0]==\"title\")}]') for e in evs]" 2>/dev/null || echo "  (no events found)"

nak-events:      ## Show recent events from this tool's Nostr identity
	@if [ -z "$(NAK_PUBKEY)" ]; then \
		echo "No pubkey available."; exit 1; fi
	$(NAK) req -k 30301 -k 30302 --limit 10 -a "$(NAK_PUBKEY)" $(NAK_RELAYS) 2>/dev/null | \
		python3 -c "import sys,json; evs=[json.loads(l) for l in sys.stdin if l.strip()]; [print(f'  kind={e[\"kind\"]} id={e[\"id\"][:12]} tags={[t[0] for t in e.get(\"tags\",[]) if len(t)>1][:5]}') for e in evs]" 2>/dev/null || echo "  (no events)"

nak-help:        ## Show nak usage and available commands
	@$(NAK) --help 2>&1 | head -30
	@echo ""
	@echo "─── Make targets for nak ───"
	@echo "  make nak-check         Verify nak is installed"
	@echo "  make nak-pubkey        Show your configured Nostr pubkey"
	@echo "  make nak-board-publish Publish kanbanstr board event"
	@echo "  make nak-board-sync    Outbound sync: local → Nostr"
	@echo "  make nak-board-inbound Inbound sync: Nostr → local"
	@echo "  make nak-pending       Query pending items from Nostr"
	@echo "  make nak-events        Show recent events"
	@echo "  make nak-help          This help"
