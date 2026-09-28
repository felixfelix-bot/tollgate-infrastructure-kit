# Adding New Services

## Overview

To add a new service to the Tollgate Infrastructure Kit:

1. Create an Ansible role
2. Create a playbook
3. Add the role to the master playbook
4. Update the Caddyfile template
5. Add DNS record (if subdomain needed)
6. Add tests
7. Update documentation

## Step-by-Step

### 1. Create the Ansible Role

```bash
mkdir -p ansible/roles/my_service/{tasks,templates,defaults,handlers,files}
```

Create `ansible/roles/my_service/tasks/main.yml`:

```yaml
---
- name: Create my_service directory
  file:
    path: "{{ tollgate_base_dir }}/my-service"
    state: directory
    mode: '0755'

- name: Deploy my_service docker-compose
  template:
    src: docker-compose.yml.j2
    dest: "{{ tollgate_base_dir }}/my-service/docker-compose.yml"
    mode: '0644'

- name: Start my_service
  community.docker.docker_compose_v2:
    project_src: "{{ tollgate_base_dir }}/my-service"
    state: present
```

### 2. Create the Playbook

Create `ansible/playbooks/NN-my-service.yml`:

```yaml
---
- name: Deploy my service
  hosts: tollgate-vps
  become: yes
  gather_facts: yes
  roles:
    - my_service
```

### 3. Add to Master Playbook

Edit `ansible/playbooks/setup-all.yml` and add `- my_service` to the roles list.

### 4. Update Caddyfile

Edit `ansible/roles/caddy/templates/Caddyfile.j2`:

```caddy
    handle myservice.{{ base_domain }} {
        reverse_proxy localhost:MY_PORT
    }
```

### 5. Add DNS Record

Edit `ansible/group_vars/all.yml` and add to `cloudflare_subdomains`:

```yaml
cloudflare_subdomains:
  - relay
  - chat
  - ...
  - myservice  # Add this
```

### 6. Add Tests

Create `tests/e2e/tests/myservice.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

const BASE_DOMAIN = process.env.BASE_DOMAIN || 'localhost';

test.describe('My Service', () => {
  test('is accessible', async ({ request }) => {
    const response = await request.get(`https://myservice.${BASE_DOMAIN}/`, {
      ignoreHTTPSErrors: true,
    });
    expect(response.status()).toBeLessThan(500);
  });
});
```

### 7. Update Documentation

Add the service to `docs/services.md` and update `README.md`.
