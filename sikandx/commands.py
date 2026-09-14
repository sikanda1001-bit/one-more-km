"""Plain-language command parser for SikandX.

Understood intents (case-insensitive):
  help | status | account
  go long / buy [N lots] [force]      -> manual buy (explicit user override)
  go short / sell [N lots] [force]    -> manual sell
  close all [positions]
  pause | stop trading | halt
  resume [target <amount>]
  set target <amount> | set new target to <amount>
  set max positions <n>
  set min score <n>
  set risk <pct>
  enable auto | disable auto
  confirm live   (typed one-time live authorization)
  revoke live
Autonomous entries (auto mode) always pass the strategy gate; manual
go long/short orders are explicit user overrides and are executed with
computed SL/TP, still subject to pause/target/max-position/live gates.
"""
import re


def _num(text: str):
    m = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
    return float(m.group(1)) if m else None


def parse_command(text: str) -> dict:
    t = (text or "").strip()
    low = t.lower()
    if not low:
        return dict(action="empty", reply="Type a command, e.g. 'status', 'go long on gold', 'set target 500'.")

    if re.search(r"\bhelp\b|\bwhat can you\b", low):
        return dict(action="help", reply=(
            "Commands: status • go long [lots] • go short [lots] • close all • pause • "
            "resume [target N] • set target N • set max positions N • set min score N • "
            "set risk N • enable auto • disable auto • CONFIRM LIVE • revoke live"))

    if low.strip() == "confirm live":
        return dict(action="confirm_live", reply="Live execution authorization recorded.")

    if re.search(r"revoke live|cancel live|disable live", low):
        return dict(action="revoke_live", reply="Live authorization revoked. Live orders blocked.")

    if re.search(r"\bstatus\b|\baccount\b|\bpositions\b.*\bshow\b", low) and "set" not in low:
        return dict(action="status", reply="Account status requested.")

    if re.search(r"close all|close everything|flatten", low):
        return dict(action="close_all", reply="Close-all requested.")

    if re.search(r"\bpause\b|\bstop trading\b|\bhalt\b", low) and "resume" not in low:
        return dict(action="pause", reply="Trading paused. No new entries until resume.")

    m = re.search(r"resume(?:.*?(?:target|to)\s*\$?\s*(\d+(?:\.\d+)?))?", low)
    if m and low.startswith("resume"):
        v = float(m.group(1)) if m.group(1) else None
        return dict(action="resume", target=v,
                    reply=(f"Resuming with new target {v}." if v else "Resuming with current target."))

    if re.search(r"set.*target|new target", low):
        v = _num(low)
        if v is None:
            return dict(action="invalid", reply="Give a target amount, e.g. 'set target 500'.")
        return dict(action="set_target", target=v, reply=f"Equity target set to {v} and persisted.")

    if re.search(r"max positions|max trades", low):
        v = _num(low)
        if v is None:
            return dict(action="invalid", reply="Give a number, e.g. 'set max positions 3'.")
        return dict(action="set_max_positions", value=int(v), reply=f"Max simultaneous positions set to {int(v)}.")

    if re.search(r"min score|minimum score|threshold", low):
        v = _num(low)
        if v is None:
            return dict(action="invalid", reply="Give a score, e.g. 'set min score 50'.")
        return dict(action="set_min_score", value=int(v), reply=f"Minimum signal score set to {int(v)}.")

    if re.search(r"\brisk\b", low) and "set" in low:
        v = _num(low)
        if v is None:
            return dict(action="invalid", reply="Give a percent, e.g. 'set risk 1'.")
        return dict(action="set_risk", value=float(v), reply=f"Risk per trade set to {v}%.")

    if re.search(r"enable auto|start auto|auto on", low):
        return dict(action="set_auto", value=True, reply="Autonomous strategy execution enabled.")
    if re.search(r"disable auto|stop auto|auto off|manual only", low):
        return dict(action="set_auto", value=False, reply="Autonomous execution disabled (manual commands only).")

    if re.search(r"\bgo long\b|\bbuy\b|\blong\b", low) and "short" not in low:
        lots = _num(low)
        force = bool(re.search(r"\bforce\b|\bnow\b|\boverride\b", low))
        return dict(action="buy", lots=lots, force=force,
                    reply=f"Manual buy request{' (explicit override)' if force or True else ''}.")
    if re.search(r"\bgo short\b|\bsell\b|\bshort\b", low):
        lots = _num(low)
        force = bool(re.search(r"\bforce\b|\bnow\b|\boverride\b", low))
        return dict(action="sell", lots=lots, force=force, reply="Manual sell request.")

    return dict(action="unknown",
                reply="I did not understand that. Try 'help' — e.g. 'go long on gold', 'close all positions', 'set target 500'.")
