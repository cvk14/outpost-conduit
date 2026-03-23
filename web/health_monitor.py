"""Background health monitor — periodic diagnostics with email alerts."""

import asyncio
import json
import logging
import os
import re
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

DEFAULT_CONFIG = {
    "health_check_interval_minutes": 15,
    "smtp_enabled": False,
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_to": "",
    "smtp_tls": True,
}


def load_config() -> dict:
    if CONFIG_PATH.is_file():
        with open(CONFIG_PATH) as f:
            saved = json.load(f)
        config = {**DEFAULT_CONFIG, **saved}
        return config
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def send_alert_email(config: dict, subject: str, body: str) -> bool:
    """Send an alert email. Returns True on success."""
    if not config.get("smtp_enabled") or not config.get("smtp_host"):
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = config["smtp_from"]
        msg["To"] = config["smtp_to"]
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain"))

        if config.get("smtp_tls"):
            server = smtplib.SMTP(config["smtp_host"], config["smtp_port"])
            server.starttls()
        else:
            server = smtplib.SMTP(config["smtp_host"], config["smtp_port"])

        if config.get("smtp_user"):
            server.login(config["smtp_user"], config["smtp_password"])

        server.sendmail(config["smtp_from"], config["smtp_to"].split(","), msg.as_string())
        server.quit()
        logger.info("Alert email sent: %s", subject)
        return True
    except Exception as e:
        logger.error("Failed to send alert email: %s", e)
        return False


class HealthMonitor:
    """Periodic health checker that runs ping + multicast tests on all sites."""

    def __init__(self, get_sites, get_inventory_path, get_output_dir):
        self.get_sites = get_sites
        self.get_inventory_path = get_inventory_path
        self.get_output_dir = get_output_dir
        self.latest_results: dict = {}
        self._task: asyncio.Task | None = None
        self._last_alert_state: dict = {}  # Track per-site alert state to avoid spam

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._monitor_loop())
            logger.info("HealthMonitor started")

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("HealthMonitor stopped")

    async def run_now(self) -> dict:
        """Run health checks immediately and return results."""
        config = load_config()
        await self._run_checks(config)
        return self.latest_results

    async def _monitor_loop(self) -> None:
        # Run first check quickly after startup
        await asyncio.sleep(10)

        while True:
            config = load_config()
            interval = max(config.get("health_check_interval_minutes", 15), 1) * 60

            try:
                await self._run_checks(config)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Health check error")

            await asyncio.sleep(interval)

    async def _run_checks(self, config: dict) -> None:
        sites = self.get_sites()
        results = {}
        problems = []

        for site in sites:
            name = site["name"]
            tunnel_ip = site["tunnel_ip"]
            site_result = {"name": name, "tunnel_ip": tunnel_ip, "timestamp": int(time.time())}

            # Ping test
            try:
                ping_data = await self._ping(tunnel_ip)
                site_result["ping"] = ping_data
                if ping_data["packet_loss_pct"] > 50:
                    problems.append(f"{name}: {ping_data['packet_loss_pct']}% packet loss")
                elif ping_data["packet_loss_pct"] == 100:
                    problems.append(f"{name}: UNREACHABLE (100% packet loss)")
            except Exception as e:
                site_result["ping"] = {"error": str(e)}
                problems.append(f"{name}: ping failed ({e})")

            # Multicast hub→site test
            try:
                mcast_out = await self._mcast_test_out(site)
                site_result["multicast_out"] = mcast_out
                if not mcast_out.get("received"):
                    problems.append(f"{name}: multicast hub\u2192site FAILED")
            except Exception as e:
                site_result["multicast_out"] = {"received": False, "error": str(e)}

            # Multicast site→hub test
            try:
                mcast_in = await self._mcast_test_in(site)
                site_result["multicast_in"] = mcast_in
                if not mcast_in.get("received"):
                    problems.append(f"{name}: multicast site\u2192hub FAILED")
            except Exception as e:
                site_result["multicast_in"] = {"received": False, "error": str(e)}

            results[name] = site_result

        self.latest_results = {
            "timestamp": int(time.time()),
            "sites": results,
            "problems": problems,
        }

        # Send alert if there are NEW problems
        if problems:
            new_problems = [p for p in problems if p not in self._last_alert_state.get("problems", [])]
            if new_problems and config.get("smtp_enabled"):
                subject = f"Outpost Conduit Alert: {len(problems)} issue(s) detected"
                body = "The following issues were detected:\n\n"
                body += "\n".join(f"  - {p}" for p in problems)
                body += f"\n\nTimestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                body += f"\nCheck interval: {config.get('health_check_interval_minutes', 15)} minutes"
                send_alert_email(config, subject, body)

        self._last_alert_state = {"problems": problems}
        logger.info("Health check complete: %d sites, %d problems", len(results), len(problems))

    async def _run_cmd(self, cmd: str) -> str:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode()

    async def _ping(self, tunnel_ip: str) -> dict:
        output = await self._run_cmd(f"ping -c 3 -W 2 {tunnel_ip}")
        result = {"packet_loss_pct": 100.0, "rtt_avg": None}

        loss_match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
        if loss_match:
            result["packet_loss_pct"] = float(loss_match.group(1))

        rtt_match = re.search(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", output)
        if rtt_match:
            result["rtt_avg"] = float(rtt_match.group(2))

        return result

    async def _mcast_test_out(self, site: dict) -> dict:
        """Test hub→site via unicast through tunnel."""
        from web.ssh_manager import run_ssh_command

        test_id = f"HM_{int(time.time())}"
        tunnel_ip = site["tunnel_ip"]

        listen_cmd = (
            "rm -f /tmp/hm_test.log; "
            "socat -u UDP4-RECVFROM:9998,reuseaddr "
            "SYSTEM:'cat >> /tmp/hm_test.log' & "
            "LPID=$!; sleep 6; kill $LPID 2>/dev/null; "
            "cat /tmp/hm_test.log 2>/dev/null; rm -f /tmp/hm_test.log"
        )
        listen_task = asyncio.create_task(run_ssh_command(site, listen_cmd, timeout=18))
        await asyncio.sleep(6)

        for _ in range(3):
            send_proc = await asyncio.create_subprocess_shell(
                f"echo '{test_id}' | socat - UDP4-SENDTO:{tunnel_ip}:9998",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await send_proc.communicate()
            await asyncio.sleep(0.5)

        output = await listen_task
        return {"received": test_id in output}

    async def _mcast_test_in(self, site: dict) -> dict:
        """Test site→hub via unicast through tunnel."""
        from web.ssh_manager import run_ssh_command

        test_id = f"HMR_{int(time.time())}"

        hub_listener = await asyncio.create_subprocess_shell(
            "timeout 10 socat -u UDP4-RECVFROM:9998,reuseaddr STDOUT",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.sleep(1)

        try:
            await run_ssh_command(
                site, f"echo '{test_id}' | socat - UDP4-SENDTO:172.27.0.1:9998", timeout=5
            )
        except Exception:
            pass

        try:
            stdout, _ = await asyncio.wait_for(hub_listener.communicate(), timeout=10)
            return {"received": test_id in stdout.decode()}
        except asyncio.TimeoutError:
            hub_listener.kill()
            return {"received": False}
