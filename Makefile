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
	ansible-lint ansible/playbooks/ ansible/roles/

check:
	@echo "Syntax check..."
	ansible-playbook -i ansible/inventory/hosts.yml ansible/playbooks/setup-all.yml --syntax-check
