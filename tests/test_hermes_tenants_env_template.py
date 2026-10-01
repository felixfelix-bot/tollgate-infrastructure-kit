#!/usr/bin/env python3
"""Unit tests for the hermes_tenants tenant config templates (A6 / t_7fa5a8bd).

Two corruptions of the same class are guarded here. Both were injected by the
repo's secret-scrubbing pass, which replaced Jinja expressions with literal
redaction placeholders:

  1. tasks/main.yml (the per-tenant .env content block): the ZAI_API_KEY line's
     opening delimiter was replaced by three asterisks, so the deployed file
     shipped `*** item.zai_api_key }}` instead of the tenant's key. Fixed at
     MT-11b (1a14e68); this test keeps it fixed.

  2. templates/config.yaml.j2 (the LLM routing config): the per-tenant routstr
     API key expression was replaced by the literal `<redacted>`, so every
     tenant's config.yaml carried a placeholder key and LLM calls failed.
     Fixed by this card (A6).

The tests render the templates directly with Jinja2 (no Ansible/molecule) and
assert the acceptance condition: the rendered file contains the actual value.

Run:
    python3 -m pytest tests/test_hermes_tenants_env_template.py -q
    python3 -m unittest tests.test_hermes_tenants_env_template -v
"""

import os
import re
import unittest

import jinja2
import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROLE = os.path.join(REPO, "ansible", "roles", "hermes_tenants")
TASKS = os.path.join(ROLE, "tasks", "main.yml")
CONFIG_J2 = os.path.join(ROLE, "templates", "config.yaml.j2")
ENV_TASK_NAME = "Deploy per-tenant .env files"

TENANT = {
    "name": "alice",
    "npub": "npub1alice",
    "nsec": "nsec1alice",
    "zai_api_key": "test-key-alice",
}
VARS = {
    "hermes_tenants_nostr_relays": "wss://relay.example",
    "hermes_tenants_nostr_groups": "grp-alice",
    "hermes_tenants_nostr_nsec_path": "/data/nsec",
    "hermes_tenants_gateway_allow_all_users": True,
    "hermes_tenants_deployment_admin_nsec": "nsec1admin",
    "hermes_tenants_routstr_api_key": "test-key-routstr",
}
ENV_KEYS = (
    "HERMES_NPUB",
    "HERMES_NSEC",
    "ZAI_API_KEY",
    "NOSTR_RELAYS",
    "NOSTR_GROUPS",
    "NOSTR_NSEC_PATH",
    "GATEWAY_ALLOW_ALL_USERS",
    "DEPLOYMENT_ADMIN_NSEC",
)

# Literal placeholders a scrubber leaves behind in place of a Jinja expression.
# The three-asterisk token is assembled at runtime so this file itself can never
# be re-scrubbed into matching its own pattern.
REDACTION_STAR = "*" * 3
PLACEHOLDER_RES = (
    re.compile(re.escape(REDACTION_STAR) + r"\s+item\."),
    re.compile(r'"\s*<\s*redacted\s*>"'),
    re.compile(r"=\s*<\s*redacted\s*>"),
)


def role_templates():
    tdir = os.path.join(ROLE, "templates")
    return [os.path.join(tdir, n) for n in sorted(os.listdir(tdir)) if n.endswith(".j2")]


def load_env_content():
    with open(TASKS) as fh:
        tasks = yaml.safe_load(fh)
    for task in tasks:
        if task.get("name") == ENV_TASK_NAME:
            return task["ansible.builtin.copy"]["content"]
    raise AssertionError("task %r not found in %s" % (ENV_TASK_NAME, TASKS))


def render_str(template_text, extra=None):
    env = dict(VARS)
    env.update(extra or {})
    env["item"] = TENANT
    tmpl = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(template_text)
    return tmpl.render(**env)


def env_map(rendered):
    out = {}
    for line in rendered.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            out[key] = value
    return out


class TestEnvTemplate(unittest.TestCase):
    """Guard 1: the per-tenant .env content block in tasks/main.yml."""

    def setUp(self):
        self.content = load_env_content()
        self.rendered = render_str(self.content)
        self.vars = env_map(self.rendered)

    def test_zai_api_key_line_is_not_mangled(self):
        self.assertNotIn(REDACTION_STAR, self.content)

    def test_zai_api_key_renders_the_actual_value(self):
        self.assertIn("ZAI_API_KEY", self.vars)
        self.assertEqual(self.vars["ZAI_API_KEY"], TENANT["zai_api_key"])

    def test_zai_api_key_value_is_not_a_residual_expression(self):
        value = self.vars["ZAI_API_KEY"]
        self.assertNotEqual(value.strip(), "")
        self.assertNotIn("item.", value)
        self.assertNotIn("{%", value)
        self.assertNotIn("}}", value)

    def test_every_declared_var_renders_a_non_empty_value(self):
        for key in ENV_KEYS:
            self.assertIn(key, self.vars, "missing %s in rendered .env" % key)
            self.assertNotEqual(self.vars[key].strip(), "", "%s rendered empty" % key)
        self.assertEqual(self.vars["GATEWAY_ALLOW_ALL_USERS"], "true")

    def test_per_tenant_key_is_selected(self):
        other = dict(TENANT, name="bob", zai_api_key="test-key-bob")
        env = dict(VARS, item=other)
        rendered = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
            self.content).render(**env)
        self.assertEqual(env_map(rendered)["ZAI_API_KEY"], "test-key-bob")

    def test_renders_without_leftover_delimiters(self):
        self.assertNotIn("{{", self.rendered)
        self.assertNotIn("}}", self.rendered)


class TestConfigYamlTemplate(unittest.TestCase):
    """Guard 2: the per-tenant LLM routing key in templates/config.yaml.j2."""

    def setUp(self):
        with open(CONFIG_J2) as fh:
            self.text = fh.read()
        self.rendered = render_str(self.text)
        self.cfg = yaml.safe_load(self.rendered)

    def test_api_key_is_templated_not_a_literal(self):
        self.assertIn("api_key", self.cfg["model"])
        self.assertEqual(self.cfg["model"]["api_key"], VARS["hermes_tenants_routstr_api_key"])
        self.assertNotIn("redacted", self.rendered.lower())
        self.assertNotIn(REDACTION_STAR, self.text)

    def test_model_block_routes_through_routstr_custom_provider(self):
        self.assertEqual(self.cfg["model"]["provider"], "custom")
        self.assertEqual(self.cfg["model"]["base_url"], "http://routstr:8000/v1")

    def test_config_renders_without_leftover_delimiters(self):
        self.assertNotIn("{{", self.rendered)
        self.assertNotIn("}}", self.rendered)

    def test_api_key_tracks_the_role_variable(self):
        rendered = render_str(self.text, extra={"hermes_tenants_routstr_api_key": "sk-other"})
        self.assertEqual(yaml.safe_load(rendered)["model"]["api_key"], "sk-other")


class TestNoScrubArtifactsInRoleTemplates(unittest.TestCase):
    """Class-level guard: no literal scrub placeholders anywhere in the templates."""

    def test_no_redaction_placeholders_in_any_role_template(self):
        offenders = []
        for path in role_templates():
            with open(path) as fh:
                text = fh.read()
            for pattern in PLACEHOLDER_RES:
                if pattern.search(text):
                    offenders.append((os.path.basename(path), pattern.pattern))
        self.assertEqual(offenders, [], "scrub placeholders left in templates: %s" % offenders)


if __name__ == "__main__":
    unittest.main()
