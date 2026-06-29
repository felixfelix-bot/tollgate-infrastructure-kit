import os
import re
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

ROLE_DIR = Path(__file__).resolve().parents[2] / "ansible" / "roles" / "fips_exit_node"
ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "ansible"


def _env():
    return Environment(
        loader=FileSystemLoader(str(ROLE_DIR / "templates")),
        variable_start_string="{{",
        variable_end_string="}}",
        keep_trailing_newline=True,
    )


def _base_vars(**overrides):
    defaults = {
        "tollgate_base_dir": "/opt/tollgate",
        "base_domain": "orangesync.tech",
        "vps_ip": "23.182.128.51",
        "ansible_default_ipv4": {"interface": "eth0"},
        "fips_exit_enabled": True,
        "fips_exit_autogen_keys": True,
        "fips_exit_wg_iface": "wgexit0",
        "fips_exit_wg_port": 51821,
        "fips_exit_tunnel_subnet": "10.99.99.0/24",
        "fips_exit_server_tunnel_ip": "10.99.99.1",
        "fips_exit_peer_tunnel_ip": "10.99.99.2",
        "fips_exit_public_iface": "eth0",
        "fips_exit_mtu": 1420,
        "fips_exit_config_dir": "/opt/tollgate/fips-exit-node",
        "fips_exit_server_private_key": "TEST_SERVER_PRIVATE_KEY_BASE64",
        "fips_exit_server_public_key": "TEST_SERVER_PUBLIC_KEY_BASE64",
        "fips_exit_peer_private_key": "TEST_PEER_PRIVATE_KEY_BASE64",
        "fips_exit_peer_public_key": "TEST_PEER_PUBLIC_KEY_BASE64",
        "fips_exit_advertise": True,
        "fips_exit_advert_kind": 30078,
        "fips_exit_advert_identifier": "tollgate-fips-exit",
        "fips_exit_advert_endpoint": "23.182.128.51:51821",
        "fips_exit_advert_interval_hours": 6,
        "fips_exit_advert_relays": [
            "wss://relay1.orangesync.tech",
            "wss://relay.damus.io",
        ],
        "fips_exit_identity_nsec": "",
    }
    defaults.update(overrides)
    return defaults


def test_defaults_yaml_is_valid():
    data = yaml.safe_load((ROLE_DIR / "defaults" / "main.yml").read_text())
    assert isinstance(data, dict)
    assert data["fips_exit_wg_iface"] == "wgexit0"
    assert data["fips_exit_wg_port"] == 51821
    assert "10.99.99" in data["fips_exit_tunnel_subnet"]
    assert data.get("fips_exit_autogen_keys") is True


def test_tasks_yaml_is_valid():
    data = yaml.safe_load((ROLE_DIR / "tasks" / "main.yml").read_text())
    assert isinstance(data, list)
    names = [t.get("name", "") for t in data if isinstance(t, dict)]
    joined = "\n".join(names)
    assert "wireguard" in joined.lower()
    assert "ip_forward" in joined.lower() or "sysctl" in joined.lower()
    assert "nft" in joined.lower()


def test_tasks_autogenerate_keys_when_not_provided():
    data = yaml.safe_load((ROLE_DIR / "tasks" / "main.yml").read_text())
    joined = yaml.safe_dump(data)
    assert "openssl rand -hex 32" in joined
    assert "identity_nsec" in joined
    assert "peer_private.key" in joined
    assert "peer_public.key" in joined
    assert "peer-client.conf" in joined


def test_handlers_yaml_is_valid():
    data = yaml.safe_load((ROLE_DIR / "handlers" / "main.yml").read_text())
    assert isinstance(data, list)
    names = [t.get("name", "") for t in data if isinstance(t, dict)]
    assert any("wg" in n.lower() or "wireguard" in n.lower() for n in names)


def test_playbook_targets_vps_and_role():
    pb = ANSIBLE_DIR / "playbooks" / "40-fips-exit-node.yml"
    data = yaml.safe_load(pb.read_text())
    assert isinstance(data, list)
    play = data[0]
    assert play["hosts"] == "vps"
    roles = play["roles"]
    assert "fips_exit_node" in roles


def test_wg_conf_renders_and_has_required_fields():
    rendered = _env().get_template("wg-exit.conf.j2").render(**_base_vars())
    assert "[Interface]" in rendered
    assert "[Peer]" in rendered
    assert "PrivateKey = TEST_SERVER_PRIVATE_KEY_BASE64" in rendered
    assert "Address = 10.99.99.1/24" in rendered
    assert "ListenPort = 51821" in rendered
    assert "MTU = 1420" in rendered
    assert "PublicKey = TEST_PEER_PUBLIC_KEY_BASE64" in rendered
    assert "AllowedIPs = 10.99.99.2/32" in rendered
    assert "net.ipv4.ip_forward=1" in rendered
    assert "exit-nat.nft" in rendered
    assert "delete table inet fips-exit" in rendered


def test_peer_client_conf_renders_for_transfer():
    rendered = _env().get_template("peer-client.conf.j2").render(**_base_vars())
    assert "[Interface]" in rendered
    assert "PrivateKey = TEST_PEER_PRIVATE_KEY_BASE64" in rendered
    assert "Address = 10.99.99.2/24" in rendered
    assert "[Peer]" in rendered
    assert "PublicKey = TEST_SERVER_PUBLIC_KEY_BASE64" in rendered
    assert "Endpoint = 23.182.128.51:51821" in rendered
    assert "AllowedIPs = 0.0.0.0/0, ::/0" in rendered
    assert "PersistentKeepalive" in rendered


def test_nft_renders_with_masquerade_and_forwarding():
    rendered = _env().get_template("exit-nat.nft.j2").render(**_base_vars())
    assert "table inet fips-exit" in rendered
    assert "type nat hook postrouting" in rendered
    assert "masquerade" in rendered
    assert 'oifname "eth0"' in rendered
    assert "10.99.99.0/24" in rendered
    assert "type filter hook forward" in rendered
    assert 'iifname "wgexit0"' in rendered
    assert "ct state established,related accept" in rendered


def test_advert_script_renders_with_route_and_endpoint():
    rendered = _env().get_template("fips-exit-advert.sh.j2").render(**_base_vars())
    assert rendered.startswith("#!/bin/bash")
    assert "FIPS_EXIT_NSEC" in rendered
    assert "identity_nsec" in rendered
    assert "nak event" in rendered
    assert "--kind 30078" in rendered
    assert "route=0.0.0.0/0" in rendered
    assert "route=::/0" in rendered
    assert "transport=wireguard" in rendered
    assert "23.182.128.51:51821" in rendered
    assert "wss://relay1.orangesync.tech" in rendered
    assert "wss://relay.damus.io" in rendered
    assert "d=tollgate-fips-exit" in rendered


def test_advert_can_be_disabled():
    rendered = _env().get_template("fips-exit-advert.sh.j2").render(
        **_base_vars(fips_exit_advertise=False)
    )
    assert rendered.startswith("#!/bin/bash")
    assert "exit 0" in rendered


def test_systemd_service_and_timer_render():
    env = _env()
    svc = env.get_template("tollgate-fips-exit-advert.service.j2").render(**_base_vars())
    assert "ExecStart=" in svc
    assert "fips-exit-advert.sh" in svc
    timer = env.get_template("tollgate-fips-exit-advert.timer.j2").render(**_base_vars())
    assert "OnBootSec=" in timer
    assert "OnUnitActiveSec=" in timer
    assert "6h" in timer
