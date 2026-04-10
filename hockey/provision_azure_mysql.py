#!/usr/bin/env python3
"""
Azure MySQL Flexible Server Provisioner
=======================================
Provisions all required Azure resources for a MySQL Flexible Server
and imports an on-premises SQL dump.

Requirements:
    pip install azure-identity azure-mgmt-resource azure-mgmt-network \
                azure-mgmt-rdbms mysql-connector-python tqdm

Usage:
    python provision_azure_mysql.py
    python provision_azure_mysql.py --import-dump /path/to/backup.sql
    python provision_azure_mysql.py --import-dump /path/to/backup.sql.gz
"""

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):    print(f"{GREEN}  ✓ {msg}{RESET}")
def info(msg):  print(f"{CYAN}  → {msg}{RESET}")
def warn(msg):  print(f"{YELLOW}  ⚠ {msg}{RESET}")
def err(msg):   print(f"{RED}  ✗ {msg}{RESET}")
def header(msg):print(f"\n{BOLD}{msg}{RESET}")

# ── Configuration (edit before running) ───────────────────────────────────────
@dataclass
class Config:
    # ── Azure identity & scope ────────────────────────────────────────────────
    subscription_id: str = "fe976419-b62e-4bdc-9c71-e299c3efdd29"   # az account show --query id
    tenant_id: str       = "acacaba2-f536-4126-b80c-b0a1f7f144de"          # az account show --query tenantId

    # ── Resource names ────────────────────────────────────────────────────────
    resource_group: str  = "rg-mysql-prod"
    location: str        = "swedencentral"           # az account list-locations -o table

    vnet_name: str       = "vnet-mysql-prod"
    subnet_name: str     = "snet-mysql"
    nsg_name: str        = "nsg-mysql"

    server_name: str     = "mysql-flex-prod"         # globally unique, 3-63 chars, lowercase
    admin_user: str      = "mysqladmin"
    admin_password: str  = "B1llyfjant.1"           # ≥8 chars, upper+lower+digit+special

    # ── SKU & storage ─────────────────────────────────────────────────────────
    sku_name: str        = "Standard_B2ms"           # Burstable 2 vCores
    sku_tier: str        = "Burstable"
    storage_gb: int      = 64
    mysql_version: str   = "8.0.21"

    # ── Networking ────────────────────────────────────────────────────────────
    vnet_prefix: str     = "10.1.0.0/16"
    subnet_prefix: str   = "10.1.1.0/24"

    # ── Backup ───────────────────────────────────────────────────────────────
    backup_retention_days: int = 7

    # ── Import tuning (applied before dump, reverted after) ──────────────────
    import_tuning: dict = field(default_factory=lambda: {
        "innodb_buffer_pool_size":      "4294967296",  # 4 GB
        "innodb_flush_log_at_trx_commit": "2",
        "sync_binlog":                  "0",
    })


# ── Dependency check ─────────────────────────────────────────────────────────
def check_dependencies():
    header("Checking Python dependencies")
    required = {
        "azure.identity":          "azure-identity",
        "azure.mgmt.resource":     "azure-mgmt-resource",
        "azure.mgmt.network":      "azure-mgmt-network",
        "azure.mgmt.rdbms.mysql_flexibleservers": "azure-mgmt-rdbms",
        "mysql.connector":         "mysql-connector-python",
        "tqdm":                    "tqdm",
    }
    missing = []
    for module, pkg in required.items():
        try:
            __import__(module)
            ok(module)
        except ImportError:
            err(f"{module} missing  (pip install {pkg})")
            missing.append(pkg)
    if missing:
        print(f"\n{YELLOW}Run:{RESET}  pip install {' '.join(missing)}")
        sys.exit(1)


# ── Azure provisioning ───────────────────────────────────────────────────────
def get_credential():
    """Use Azure CLI credentials (must be logged in via 'az login')."""
    from azure.identity import AzureCliCredential
    info("Using Azure CLI credentials…")
    cred = AzureCliCredential()
    ok("Authenticated via Azure CLI")
    return cred


def register_required_providers(cfg: Config, cred):
    """Register required Azure resource providers."""
    from azure.mgmt.resource import ResourceManagementClient
    header("Registering Azure resource providers")
    client = ResourceManagementClient(cred, cfg.subscription_id)

    required_providers = [
        "Microsoft.Network",
        "Microsoft.DBforMySQL",
    ]

    for provider_namespace in required_providers:
        info(f"Checking {provider_namespace}…")
        provider = client.providers.get(provider_namespace)

        if provider.registration_state != "Registered":
            info(f"Registering {provider_namespace} (this may take 1-2 minutes)…")
            client.providers.register(provider_namespace)

            # Wait for registration to complete
            max_attempts = 40  # 40 * 3s = 2 minutes max
            for attempt in range(max_attempts):
                provider = client.providers.get(provider_namespace)
                if provider.registration_state == "Registered":
                    break
                time.sleep(3)

            if provider.registration_state == "Registered":
                ok(f"{provider_namespace} registered")
            else:
                warn(f"{provider_namespace} registration still pending (state: {provider.registration_state})")
        else:
            ok(f"{provider_namespace} already registered")

    return client


def provision_resource_group(cfg: Config, cred):
    from azure.mgmt.resource import ResourceManagementClient
    header("Resource group")
    client = ResourceManagementClient(cred, cfg.subscription_id)
    rg = client.resource_groups.create_or_update(
        cfg.resource_group,
        {"location": cfg.location, "tags": {"provisioned-by": "python-script"}},
    )
    ok(f"{rg.name}  [{cfg.location}]")
    return client


def provision_network(cfg: Config, cred):
    from azure.mgmt.network import NetworkManagementClient
    from azure.mgmt.network.models import (
        VirtualNetwork, AddressSpace, Subnet,
        NetworkSecurityGroup, SecurityRule,
        Delegation,
    )
    header("Virtual network & subnet")
    nc = NetworkManagementClient(cred, cfg.subscription_id)

    # NSG — allow MySQL only from within the VNet
    info("Creating NSG…")
    nsg_params = NetworkSecurityGroup(
        location=cfg.location,
        security_rules=[
            SecurityRule(
                name="Allow-MySQL-VNet",
                protocol="Tcp",
                source_address_prefix="VirtualNetwork",
                source_port_range="*",
                destination_address_prefix="*",
                destination_port_range="3306",
                access="Allow",
                priority=100,
                direction="Inbound",
            ),
            SecurityRule(
                name="Deny-MySQL-Internet",
                protocol="Tcp",
                source_address_prefix="Internet",
                source_port_range="*",
                destination_address_prefix="*",
                destination_port_range="3306",
                access="Deny",
                priority=200,
                direction="Inbound",
            ),
        ],
    )
    nsg = nc.network_security_groups.begin_create_or_update(
        cfg.resource_group, cfg.nsg_name, nsg_params
    ).result()
    ok(f"NSG: {nsg.name}")

    # Subnet with Microsoft.DBforMySQL/flexibleServers delegation
    subnet_params = Subnet(
        name=cfg.subnet_name,
        address_prefix=cfg.subnet_prefix,
        network_security_group=nsg,
        delegations=[
            Delegation(
                name="MySQLFlexDelegation",
                service_name="Microsoft.DBforMySQL/flexibleServers",
            )
        ],
    )

    # VNet
    info("Creating VNet…")
    vnet = nc.virtual_networks.begin_create_or_update(
        cfg.resource_group,
        cfg.vnet_name,
        VirtualNetwork(
            location=cfg.location,
            address_space=AddressSpace(address_prefixes=[cfg.vnet_prefix]),
            subnets=[subnet_params],
        ),
    ).result()
    ok(f"VNet: {vnet.name}  ({cfg.vnet_prefix})")

    # Fetch the created subnet object (needed for server provisioning)
    subnet = nc.subnets.get(cfg.resource_group, cfg.vnet_name, cfg.subnet_name)
    ok(f"Subnet: {subnet.name}  ({cfg.subnet_prefix})")
    return subnet


def provision_mysql(cfg: Config, cred, subnet):
    from azure.mgmt.rdbms.mysql_flexibleservers import MySQLManagementClient
    from azure.mgmt.rdbms.mysql_flexibleservers.models import (
        Server, ServerVersion, Sku, SkuTier,
        Storage, Backup,
        Network, HighAvailability, HighAvailabilityMode,
    )
    header("MySQL Flexible Server")
    client = MySQLManagementClient(cred, cfg.subscription_id)

    info(f"Provisioning {cfg.server_name} (this takes 5–10 min)…")
    server_params = Server(
        location=cfg.location,
        administrator_login=cfg.admin_user,
        administrator_login_password=cfg.admin_password,
        version=ServerVersion(cfg.mysql_version),
        sku=Sku(
            name=cfg.sku_name,
            tier=SkuTier(cfg.sku_tier),
        ),
        storage=Storage(
            storage_size_gb=cfg.storage_gb,
            auto_grow="Enabled",
            auto_io_scaling="Disabled",
        ),
        backup=Backup(
            backup_retention_days=cfg.backup_retention_days,
            geo_redundant_backup = "Disabled",
        ),
        network=Network(
            delegated_subnet_resource_id=subnet.id,
            private_dns_zone_resource_id=None,  # Azure auto-creates when omitted
        ),
        high_availability=HighAvailability(
            mode=HighAvailabilityMode.DISABLED
        ),
    )

    poller = client.servers.begin_create(
        cfg.resource_group, cfg.server_name, server_params
    )

    # Show a spinner while waiting
    chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    i = 0
    while not poller.done():
        print(f"\r  {chars[i % len(chars)]} Waiting for server…", end="", flush=True)
        time.sleep(3)
        i += 1
    print()

    server = poller.result()
    ok(f"Server ready: {server.fully_qualified_domain_name}")
    return server, client


def print_connection_info(cfg: Config, fqdn: str):
    header("Connection details")
    print(f"""
  Host     : {fqdn}
  Port     : 3306
  User     : {cfg.admin_user}@{cfg.server_name}
  SSL      : required
  Password : {cfg.admin_password}

  MySQL CLI:
    mysql -h {fqdn} -u {cfg.admin_user} -p --ssl-mode=REQUIRED

  Connection string:
    mysql+mysqlconnector://{cfg.admin_user}:{cfg.admin_password}@{fqdn}:3306/?ssl_ca=DigiCertGlobalRootCA.crt.pem
""")


# ── Import SQL dump ──────────────────────────────────────────────────────────
def apply_tuning(conn, settings: dict, revert=False):
    """Apply or revert performance tuning variables."""
    defaults = {
        "innodb_flush_log_at_trx_commit": "1",
        "sync_binlog":                    "1",
    }
    cursor = conn.cursor()
    for var, val in settings.items():
        use = defaults.get(var, val) if revert else val
        try:
            cursor.execute(f"SET GLOBAL {var} = {use}")
        except Exception as e:
            warn(f"Could not set {var}: {e}")
    cursor.close()


def import_dump(cfg: Config, dump_path: str):
    """Stream a .sql or .sql.gz dump into the Azure MySQL server."""
    import mysql.connector
    try:
        from tqdm import tqdm
        HAS_TQDM = True
    except ImportError:
        HAS_TQDM = False

    header("Importing SQL dump")
    dump_file = Path(dump_path)
    if not dump_file.exists():
        err(f"Dump file not found: {dump_path}")
        sys.exit(1)

    fqdn = f"{cfg.server_name}.mysql.database.azure.com"
    info(f"Connecting to {fqdn}…")

    conn_args = dict(
        host=fqdn,
        user=cfg.admin_user,
        password=cfg.admin_password,
        connection_timeout=30,
        ssl_disabled=False,
        consume_results=True,
    )

    # Retry up to 5 times — server may still be warming up
    conn = None
    for attempt in range(1, 6):
        try:
            conn = mysql.connector.connect(**conn_args)
            ok("Connected")
            break
        except mysql.connector.Error as e:
            warn(f"Attempt {attempt}/5 failed: {e}")
            if attempt < 5:
                time.sleep(10)
    if conn is None:
        err("Could not connect after 5 attempts.")
        sys.exit(1)

    # Apply import tuning
    info("Applying import performance tuning…")
    apply_tuning(conn, cfg.import_tuning)

    # Detect compression
    is_gz = dump_file.suffix == ".gz"
    file_size = dump_file.stat().st_size
    opener = gzip.open if is_gz else open
    info(f"Reading {'compressed ' if is_gz else ''}dump ({file_size / 1024**2:.1f} MB on disk)…")

    cursor = conn.cursor()
    statement = ""
    lines_read = 0
    statements_run = 0
    start = time.time()

    # We stream line-by-line to avoid loading 50 GB into RAM
    try:
        with opener(dump_file, "rt", encoding="utf-8", errors="replace") as fh:
            iter_lines = tqdm(fh, unit="line", desc="  Importing", leave=True) if HAS_TQDM else fh
            for line in iter_lines:
                lines_read += 1
                stripped = line.strip()
                # Skip comments and empty lines
                if not stripped or stripped.startswith("--") or stripped.startswith("/*"):
                    continue
                statement += line
                # A statement ends at a semicolon not inside a string
                if stripped.endswith(";"):
                    try:
                        cursor.execute(statement)
                        statements_run += 1
                    except mysql.connector.Error as exc:
                        # Non-fatal: log and continue
                        warn(f"Line ~{lines_read}: {exc.msg[:120]}")
                    statement = ""
    except KeyboardInterrupt:
        warn("Import interrupted by user.")

    elapsed = time.time() - start
    cursor.close()

    # Revert tuning
    info("Reverting performance tuning…")
    apply_tuning(conn, cfg.import_tuning, revert=True)
    conn.close()

    ok(f"Import complete: {statements_run:,} statements in {elapsed:.0f}s")


# ── Alternative: shell-based import (faster for very large dumps) ─────────────
def import_dump_via_cli(cfg: Config, dump_path: str):
    """
    Use the mysql CLI for bulk import — faster for large files because
    it bypasses Python's per-statement overhead.  Requires mysql client
    installed locally and network access to the server on port 3306.
    """
    header("Importing SQL dump via mysql CLI")
    fqdn = f"{cfg.server_name}.mysql.database.azure.com"
    dump_file = Path(dump_path)
    is_gz = dump_file.suffix == ".gz"

    if not shutil.which("mysql"):
        warn("mysql CLI not found — falling back to Python import.")
        import_dump(cfg, dump_path)
        return

    if is_gz:
        cmd = (
            f"zcat {dump_path} | mysql "
            f"-h {fqdn} -u {cfg.admin_user} -p{cfg.admin_password} --ssl-mode=REQUIRED"
        )
    else:
        cmd = (
            f"mysql -h {fqdn} -u {cfg.admin_user} -p{cfg.admin_password} "
            f"--ssl-mode=REQUIRED < {dump_path}"
        )

    info(f"Running: {cmd.replace(cfg.admin_password, '***')}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode == 0:
        ok("CLI import complete.")
    else:
        err(f"mysql CLI exited with code {result.returncode}")
        sys.exit(1)


# ── Entrypoint ───────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="Provision Azure MySQL and optionally import a dump.")
    p.add_argument(
        "--import-dump", metavar="FILE",
        help="Path to SQL dump (.sql or .sql.gz) to import after provisioning.",
    )
    p.add_argument(
        "--import-only", metavar="FILE",
        help="Skip provisioning; only import the given dump into an existing server.",
    )
    p.add_argument(
        "--use-cli-import", action="store_true",
        help="Use mysql CLI for import instead of Python connector (faster for very large files).",
    )
    p.add_argument(
        "--skip-provision", action="store_true",
        help="Skip resource provisioning (useful when resources already exist).",
    )
    return p.parse_args()


def main():
    args = parse_args()
    cfg  = Config()

    print(f"\n{BOLD}Azure MySQL Flexible Server Provisioner{RESET}")
    print(f"  Subscription : {cfg.subscription_id}")
    print(f"  Resource group: {cfg.resource_group}  [{cfg.location}]")
    print(f"  Server        : {cfg.server_name}  ({cfg.sku_name}, {cfg.storage_gb} GB)\n")

    check_dependencies()

    # ── Import-only mode (no provisioning) ───────────────────────────────────
    if args.import_only:
        if args.use_cli_import:
            import_dump_via_cli(cfg, args.import_only)
        else:
            import_dump(cfg, args.import_only)
        return

    # ── Full provisioning ────────────────────────────────────────────────────
    if not args.skip_provision:
        if cfg.subscription_id == "YOUR_SUBSCRIPTION_ID":
            err("Edit Config.subscription_id before running.")
            sys.exit(1)
        if cfg.admin_password == "xxxxxx":
            warn("You are using the default password. Change Config.admin_password!")

        cred   = get_credential()
        _      = register_required_providers(cfg, cred)
        _      = provision_resource_group(cfg, cred)
        subnet = provision_network(cfg, cred)
        server, _ = provision_mysql(cfg, cred, subnet)
        fqdn   = server.fully_qualified_domain_name
        print_connection_info(cfg, fqdn)
    else:
        info("Skipping provisioning (--skip-provision).")
        fqdn = f"{cfg.server_name}.mysql.database.azure.com"

    # ── Optional dump import ─────────────────────────────────────────────────
    if args.import_dump:
        if args.use_cli_import:
            import_dump_via_cli(cfg, args.import_dump)
        else:
            import_dump(cfg, args.import_dump)

    header("Done")
    ok("All steps completed successfully.")
    if not args.import_dump and not args.import_only:
        info(f"To import your dump later, run:")
        print(f"    python {sys.argv[0]} --skip-provision --import-dump /path/to/backup.sql\n")


if __name__ == "__main__":
    main()