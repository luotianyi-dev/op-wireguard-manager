import os
import toml
import argparse

PATH_SSH = ".ssh/authorized_keys"
PATH_SYSTEMD_NETWORKD = "/etc/systemd/network"
PATH_WIREGUARD_PRIVKEY = "/etc/wireguard/privatekey"
PATH_TEMPLATES = os.path.join(os.path.dirname(__file__), "templates")
TEMPLATES = {}
EOL = "\n"

def read_config():
    config = toml.load(os.path.join(os.path.dirname(__file__), "config.toml"))
    for node in config["node"]:
        node["private-ip"] = config["address"].format(id=node["id"])
        node["routes"] = []
    return config

def read_node(config):
    node = next(filter(lambda x: x["name"] == os.uname().nodename.split(".")[0], config["node"]))
    read_wireguard_privkey(node)
    return node

def read_wireguard_privkey(node):
    with open(PATH_WIREGUARD_PRIVKEY) as f:
        print(f"Reading private key from {f.name}")
        node["wg-privkey"] = f.read().strip()

def read_template(template_name):
    with open(f"{PATH_TEMPLATES}/{template_name}") as f:
        TEMPLATES[template_name] = f.read()

def purge_systemd_networkd(config):
    print(f"Purging old systemd-networkd config")
    for filename in os.listdir(PATH_SYSTEMD_NETWORKD):
        if filename.startswith(str(config["systemd"]["networkd-importance"])):
            filepath = os.path.join(PATH_SYSTEMD_NETWORKD, filename)
            print(f"    Removing: {filepath}")
            os.remove(filepath)

def write_ssh_keys(config):
    with open(os.path.join(config["ssh"]["user-home"], PATH_SSH), "w+", encoding="utf-8") as f:
        print(f"Writing: {f.name}")
        for key in config["ssh"]["key"]:
            print(f"    Adding user ssh key: {key}")
            f.write(f"{key}{EOL}")
        for key in [x["ssh-key"] for x in config["node"]]:
            print(f"    Adding node ssh key: {key}")
            f.write(f"{key}{EOL}")

def write_systemd_networkd(config, node):
    for peer_id in node["peers"]:
        print(f"Generating config for peer {peer_id}")
        peer = next(filter(lambda x: x["id"] == peer_id, config["node"]))
        config_basename = f"{config['systemd']['networkd-importance']}-wg{peer['id']}"
        kwargs = {
            "peer_id": peer["id"],
            "node_id": node["id"],
            "peer_public_ip": peer["public-ip"],
            "peer_private_ip": config["address"].format(id=peer["id"]),
            "node_private_ip": node["private-ip"],
            "peer_pubkey": peer["wg-pubkey"],
            "node_privkey": node["wg-privkey"],
        }
        with open(f"{PATH_SYSTEMD_NETWORKD}/{config_basename}.netdev", "w+", encoding="utf-8") as f:
            print(f"    Writing: {f.name}")
            f.write(TEMPLATES["systemd.netdev"].format(**kwargs))
            f.write(EOL)
        with open(f"{PATH_SYSTEMD_NETWORKD}/{config_basename}.network", "w+", encoding="utf-8") as f:
            print(f"    Writing: {f.name}")
            f.write(TEMPLATES["systemd.network"].format(**kwargs))
            f.write(EOL)
            # adding node routes
            for route in node["routes"]:
                if not route["type"] == "kernel":
                    f.write(TEMPLATES["systemd.network-route"].format(
                        network=route["network"] + "/32",
                        gateway=route["gateway"],
                    ))
                    f.write(EOL)
            # adding docker routes
            for docker_id in config["docker"]["host"]:
                if docker_id == node["id"]:
                    continue
                for i in range(10):
                    f.write(TEMPLATES["systemd.network-route"].format(
                        network=config["docker"]["address"].format(id=docker_id, i=i),
                        gateway=config["address"].format(id=docker_id),
                    ))
                    f.write(EOL)
            f.write(EOL)

def reload_services():
    print("Reloading services")
    os.system("systemctl daemon-reload")
    os.system("systemctl restart systemd-networkd")

def display_node_info(node):
    print(f"Node \"{node['name']}\" Information")
    for key, value in node.items():
        print(f"    {key}: {value}")

def display_routing_table(config):
    print("Routing Table:")
    for node in config["node"]:
        print(f"    Node {node['private-ip']} ({node['name']})")
        for route in node["routes"]:
            print(f"        [{route['type']}] {route['network']} via {route['gateway']} on {route['device']}")

def sim_add_route(on_node, network, gateway, device, type, slient=False):
    if on_node["private-ip"] == network:
        if not slient:
            print(f"        {on_node['private-ip']}: The network is same as my ip address, ignoring")
        return
    if any(route["network"] == network for route in on_node["routes"]):
        if not slient:
            print(f"        {on_node['private-ip']}: I already have route to {network}")
        return
    if not type == "kernel":
        if not slient:
            print(f"        {on_node['private-ip']}: I don't have route to {network}, adding it")
    on_node["routes"].append({
        "network": network,
        "gateway": gateway,
        "device": device,
        "type": type
    })

def sim_node_converged(config, node):
    node_routing_table = [i["network"] for i in node["routes"]]
    node_routing_table.append(node["private-ip"])
    needed_routes = [i["private-ip"] for i in config["node"]]
    for i in needed_routes:
        if i not in node_routing_table:
            return False
    return True

def sim_system_converged(config):
    for i in config["node"]:
        if not sim_node_converged(config, i):
            return False
    return True

def sim_routing_protocol(config, silent=False):
    # adding kernel routes
    for node in config["node"]:
        for peer_id in node["peers"]:
            peer = next(filter(lambda x: x["id"] == peer_id, config["node"]))
            sim_add_route(node, peer["private-ip"], "---", f"wg{peer['id']}", "kernel", silent)

    # running routing protocol
    loop_count = 1
    if not silent:
        print("Starting routing protocol simulation")
    while not sim_system_converged(config):
        if not silent:
            print(f"    Loop {loop_count}")
        for node in config["node"]:
            for peer_id in node["peers"]:
                peer = next(filter(lambda x: x["id"] == peer_id, config["node"]))
                for route in node["routes"]:
                    if not silent:
                        print(f"        {node['private-ip']} -> {peer['private-ip']}: I have route to {route['network']}")
                    sim_add_route(peer, route["network"], node["private-ip"], "---", "netgen", silent)
        loop_count += 1
        if not silent:
            print("            Is system converged? " + str(sim_system_converged(config)))

def generate(config, node):
    for template_name in os.listdir(PATH_TEMPLATES):
        read_template(template_name)
    display_node_info(node)
    write_ssh_keys(config)
    purge_systemd_networkd(config)
    write_systemd_networkd(config, node)
    reload_services()

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Generate config files")
    return parser.parse_args()

def main():
    args = parse_args()
    config = read_config()
    node = read_node(config)
    sim_routing_protocol(config, silent=args.apply)
    if not args.apply:
        return display_routing_table(config)
    else:    
        return generate(config, node)

if __name__ == "__main__":
    main()

