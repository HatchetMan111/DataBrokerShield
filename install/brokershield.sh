#!/usr/bin/env bash
#===============================================================================
# BrokerShield – Proxmox VE Installer (Community-Scripts-Stil)
#-------------------------------------------------------------------------------
# Erstellt einen unprivilegierten LXC-Container (Debian 13) und installiert
# darin BrokerShield – ein lokales Dashboard für digitale Souveränität:
# Löschungsanfragen an 770+ Datenbroker (DSGVO Art. 17 / CCPA / generisch)
# verwalten, Status verfolgen, Wiedervorlagen für Re-Checks, optionaler
# Ollama-Assistent (extern) und SMTP-Versand. Läuft komplett lokal, keine
# Cloud, keine Accounts.
#
# Broker-Seed: eraser (https://github.com/digisamroc/eraser, MIT) + kuratierte
# EU-/DE-Broker (SCHUFA, Boniversum, CRIF, ...) – siehe app/seed.py.
#
# Einzeiler auf dem Proxmox-Host:
#   bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/DataBrokerShield/main/install/brokershield.sh)"
#
# Debug-Ablauf (vollständiges bash -x Log):
#   DEBUG=1 bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/DataBrokerShield/main/install/brokershield.sh)"
#
# Weitere Aufrufe:
#   ./brokershield.sh --update        # neuesten Stand im vorhandenen CT installieren
#   ./brokershield.sh --uninstall     # Container vollständig entfernen (DESTRUKTIV!)
#   CTID=160 VAR_CPU=2 ./brokershield.sh   # nicht-interaktiv mit eigenen Werten
#===============================================================================
set -Eeuo pipefail

#==============================
# Konfiguration (per Env überschreibbar)
#==============================
readonly APP_ID="brokershield"
readonly APP_NAME="BrokerShield"
readonly UPSTREAM_REPO="HatchetMan111/DataBrokerShield"

# BrokerShield ist ein leichtgewichtiges Dashboard (FastAPI + SQLite):
# keine neuronale Inferenz, kein Build-Schritt – Standardwerte genügen.
VAR_DISK="${VAR_DISK:-8}"         # GB
VAR_CPU="${VAR_CPU:-2}"
VAR_RAM="${VAR_RAM:-2048}"        # MB
VAR_SWAP="${VAR_SWAP:-512}"       # MB

VAR_OS="debian"
VAR_VERSION="13"
CT_TYPE="1"                       # 1 = unprivileged
BRIDGE="${BRIDGE:-vmbr0}"
NET_MODE="${NET_MODE:-dhcp}"      # dhcp | static
NET_CIDR="${NET_CIDR:-}"          # z. B. 192.168.1.100/24 (bei NET_MODE=static)
NET_GW="${NET_GW:-}"              # z. B. 192.168.1.1

WEB_PORT="${WEB_PORT:-8080}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-brokershield}"

MODE="${MODE:-install}"           # install | update | uninstall
DEBUG="${DEBUG:-0}"
GUEST_LOG_FILE="/var/log/${APP_ID}-install.log"

TARGET_CTID=""
STORAGE=""
TEMPLATE=""
NET_CFG="ip=dhcp"

TMPDIR_INSTALL="$(mktemp -d /tmp/${APP_ID}-install.XXXXXX)"
LOG_FILE="/tmp/${APP_ID}-install-$(date +%Y%m%d-%H%M%S).log"

trap 'rm -rf "$TMPDIR_INSTALL"' EXIT

#==============================
# Logging + vollständige Fehlermeldungskette
# ALLE Logzeilen gehen nach stderr, damit stdout für Funktionsrückgaben
# (resolve_self) sauber bleibt.
#==============================
exec > >(tee -a "$LOG_FILE") 2>&1

msg_info()  { printf '\033[1;36m[Info]\033[0m  %s\n' "$*" >&2; }
msg_ok()    { printf '\033[1;32m [OK]\033[0m  %s\n' "$*" >&2; }
msg_warn()  { printf '\033[1;33m [WARN]\033[0m %s\n' "$*" >&2; }
msg_error() { printf '\033[1;31m[Fehler]\033[0m %s\n' "$*" >&2; }

die() {
  msg_error "$*"
  msg_error "Komplettes Installationslog: $LOG_FILE"
  exit 1
}

enable_debug() {
  PS4='+ $(date +%H:%M:%S) [${BASH_SOURCE##*/}:${LINENO}] '
  set -x
  msg_warn "Debug-Modus aktiv (bash -x) – jede Anweisung wird ins Log mitgeschrieben."
}

print_call_stack() {
  local frame=0 line func file
  while IFS=' ' read -r line func file; do
    msg_error "  aufrufend: ${func}() (${file}:${line})"
    frame=$((frame + 1))
  done < <(while caller "$frame" 2>/dev/null; do frame=$((frame + 1)); done)
}

on_error() {
  local exit_code="$1"
  local failed_cmd="$2"
  trap - ERR
  set +Eeuo pipefail

  printf '\n' >&2
  msg_error "Installationsfehler – vollständige Fehlermeldungskette:"
  msg_error "Exit-Code : ${exit_code}"
  msg_error "Fehlschlag: ${failed_cmd}"
  print_call_stack

  if [[ "${PHASE:-host}" == "guest" ]]; then
    msg_error "--- systemctl status ${APP_ID} ---"
    systemctl --no-pager -l status "$APP_ID" 2>&1 | tail -n 25 || true
    msg_error "--- journalctl -u ${APP_ID} (letzte 40 Zeilen) ---"
    journalctl --no-pager -n 40 -u "$APP_ID" 2>&1 || true
    msg_error "--- offene Ports (ss -tlnp) ---"
    ss -tlnp 2>/dev/null || true
    msg_error "--- Speicher/Platte ---"
    free -m 2>/dev/null || true
    df -h / 2>/dev/null || true
    msg_error "Gast-Log: ${GUEST_LOG_FILE} (pct enter \$CTID → less ${GUEST_LOG_FILE})"
  fi

  msg_error "Alle Ausgaben wurden mitgeschrieben: ${LOG_FILE} (Phase: ${PHASE:-host})"
  msg_error "Zum Nachvollziehen mit vollem Shelltrace erneut ausführen:"
  msg_error "  DEBUG=1 bash -c \"\$(wget -qLO - ${SCRIPT_URL})\""
  exit "$exit_code"
}

trap 'on_error $? "$BASH_COMMAND"' ERR

if [[ "$DEBUG" == "1" ]]; then
  enable_debug
fi

PHASE="${BS_PHASE:-host}"

#==============================
# Hilfsfunktionen
#==============================
have() { command -v "$1" >/dev/null 2>&1; }

ask_default() { # ask_default <Prompt> <Default>
  local reply=""
  if [[ -t 0 ]]; then
    read -r -p "$1 [$2]: " reply </dev/tty || reply=""
    printf '%s\n' "${reply:-$2}"
  else
    msg_info "$1 → nicht-interaktiv, verwende Default: $2"
    printf '%s\n' "$2"
  fi
}

ask_required_value() { # ask_required_value <Option> <Wert>
  if (($# < 2)) || [[ -z "$2" ]]; then
    die "Option $1 benötigt einen Wert (--help anzeigen)."
  fi
  printf '%s\n' "$2"
}

confirm_or_die() { # confirm_or_die <Frage>
  if [[ -t 0 ]]; then
    local reply=""
    read -r -p "$1 [y/N]: " reply </dev/tty || reply=""
    case "$reply" in y|Y|ja|JA|Ja) return 0 ;; *) die "Abgebrochen." ;; esac
  else
    die "$1 – nicht-interaktiv und Bestätigung erforderlich (TTY fehlt)."
  fi
}

fetch_to() { # fetch_to <URL> <Zieldatei>
  local url="$1" out="$2" attempt
  for attempt in 1 2 3; do
    if curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 15 -o "${out}.part" "$url"; then
      mv "${out}.part" "$out"
      return 0
    fi
    msg_warn "Download-Versuch ${attempt}/3 fehlgeschlagen: $url"
    sleep 2
  done
  die "Konnte Datei nicht laden: $url"
}

wait_for_http() { # wait_for_http <URL> <Timeout-Sekunden>
  local url="$1" timeout_s="$2" elapsed=0 code=""
  until code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null)" && [[ "$code" =~ ^(200|301|302|307|308|401)$ ]]; do
    if (( elapsed >= timeout_s )); then
      msg_error "HTTP-Check fehlgeschlagen nach ${timeout_s}s: $url (letzter Code: ${code:-keiner})"
      return 1
    fi
    sleep 3
    elapsed=$((elapsed + 3))
  done
  return 0
}

require_active_unit() { # require_active_unit <unit>
  if ! systemctl is-active --quiet "$1"; then
    msg_error "systemd-Unit '$1' ist NICHT aktiv (Status: $(systemctl is-active "$1" 2>&1 || true))"
    journalctl --no-pager -u "$1" -n 30 2>&1 || true
    return 1
  fi
  msg_ok "Service läuft: $1"
}

#==============================
# GAST-PHASE: Installation im LXC (Debian 13)
#==============================
APT_UPDATED=0
apt_install() {
  if (( APT_UPDATED == 0 )); then
    msg_info "apt-get update …"
    DEBIAN_FRONTEND=noninteractive apt-get update -qq
    APT_UPDATED=1
  fi
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
}

install_app() {
  msg_info "Installiere System-Abhängigkeiten …"
  apt_install build-essential ca-certificates curl jq git python3 python3-venv python3-pip
  msg_ok "System-Abhängigkeiten installiert."

  msg_info "Lade BrokerShield aus dem Repo (${UPSTREAM_REPO}) …"
  rm -rf /opt/brokershield-src
  if ! git clone -q --depth 1 "https://github.com/${UPSTREAM_REPO}.git" /opt/brokershield-src; then
    die "Konnte ${UPSTREAM_REPO} nicht klonen – Repo-URL im Installer korrekt gesetzt?"
  fi
  [[ -d /opt/brokershield-src/app ]] || die "Repo-Struktur unerwartet (app/ fehlt)."
  mkdir -p /opt/brokershield
  rm -rf /opt/brokershield/app
  cp -r /opt/brokershield-src/app /opt/brokershield/app
  cp /opt/brokershield-src/requirements.txt /opt/brokershield/requirements.txt
  git -C /opt/brokershield-src rev-parse HEAD > /opt/brokershield/installed_commit.txt
  rm -rf /opt/brokershield-src
  msg_ok "App-Code übertragen (Commit $(cut -c1-7 /opt/brokershield/installed_commit.txt))."

  create_service_user
  create_venv
  write_data_dirs
  write_env_file
  start_service
}

create_service_user() {
  if id -u "$APP_ID" >/dev/null 2>&1; then
    msg_ok "Dienstbenutzer '${APP_ID}' existiert bereits."
    return 0
  fi
  useradd --system --home-dir /var/lib/brokershield --shell /usr/sbin/nologin "$APP_ID"
  msg_ok "Dienstbenutzer '${APP_ID}' angelegt."
}

create_venv() {
  if [[ -x /opt/brokershield/venv/bin/python && -x /opt/brokershield/venv/bin/uvicorn ]]; then
    msg_info "venv vorhanden – prüfe Abhängigkeiten …"
    /opt/brokershield/venv/bin/pip install --no-cache-dir --quiet -r /opt/brokershield/requirements.txt || die "pip-Update der Abhängigkeiten fehlgeschlagen."
  else
    msg_info "Erstelle Python-Umgebung (FastAPI, SQLAlchemy, …) …"
    python3 -m venv /opt/brokershield/venv
    /opt/brokershield/venv/bin/pip install --no-cache-dir --timeout 300 -r /opt/brokershield/requirements.txt \
      || die "pip install fehlgeschlagen – kompletter pip-Output steht oben im Log."
  fi
  msg_ok "Python-Umgebung fertig."
}

write_data_dirs() {
  msg_info "Lege Datenverzeichnisse an (/var/lib/brokershield) …"
  install -d -o brokershield -g brokershield -m 0750 \
    /var/lib/brokershield /var/lib/brokershield/data \
    /etc/brokershield
  # DB liegt außerhalb von /opt → überlebt App-Updates (cp -r überschreibt /opt).
  if [[ -f /opt/brokershield/data/brokershield.db && ! -f /var/lib/brokershield/data/brokershield.db ]]; then
    mv /opt/brokershield/data/brokershield.db /var/lib/brokershield/data/brokershield.db
  fi
  chown -R brokershield:brokershield /opt/brokershield /var/lib/brokershield /etc/brokershield
  msg_ok "Datenverzeichnisse angelegt."
}

write_env_file() {
  if [[ ! -f /etc/brokershield/brokershield.env ]]; then
    cat > /etc/brokershield/brokershield.env <<ENV
BROKERSHIELD_ADMIN_PASSWORD=${ADMIN_PASSWORD}
ENV
    chmod 600 /etc/brokershield/brokershield.env
    chown brokershield:brokershield /etc/brokershield/brokershield.env
    msg_ok "Env-Datei erstellt (Admin-Passwort gesetzt – bitte ändern!)."
  else
    msg_ok "Env-Datei existiert – Passwort/Settings bleiben erhalten."
  fi
}

write_systemd_unit() {
  msg_info "Schreibe systemd-Unit ${APP_ID}.service …"
  cat > /etc/systemd/system/${APP_ID}.service <<UNIT
[Unit]
Description=BrokerShield – lokales Datenbroker-Lösch-Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_ID}
Group=${APP_ID}
WorkingDirectory=/opt/brokershield
Environment=PYTHONUNBUFFERED=1
Environment=BROKERSHIELD_DB=/var/lib/brokershield/data/brokershield.db
EnvironmentFile=-/etc/brokershield/brokershield.env
ExecStart=/opt/brokershield/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${WEB_PORT} --timeout-graceful-shutdown 5
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=/var/lib/brokershield /etc/brokershield
UNIT
  chmod 644 /etc/systemd/system/${APP_ID}.service
  msg_ok "systemd-Unit geschrieben (bind 0.0.0.0:${WEB_PORT}, Restart=always)."
}

start_service() {
  write_systemd_unit
  systemctl daemon-reload
  systemctl enable ${APP_ID} >/dev/null 2>&1 || true
  msg_ok "${APP_ID}.service aktiviert (Autostart beim Boot, Restart=always)."
  msg_info "(Re)starte Service …"
  systemctl restart ${APP_ID}
}

verify_service_and_web() {
  require_active_unit "${APP_ID}" || die "${APP_ID}-Service läuft nicht – Diagnose siehe oben."

  msg_info "Warte auf Web-UI unter 127.0.0.1:${WEB_PORT} (max. 60 s) …"
  wait_for_http "http://127.0.0.1:${WEB_PORT}/healthz" 60 || {
    journalctl --no-pager -n 40 -u ${APP_ID} 2>&1 || true
    die "Web-UI antwortet nicht auf Port ${WEB_PORT}."
  }
  msg_ok "Web-UI antwortet auf 127.0.0.1:${WEB_PORT}/healthz (HTTP 200)."

  msg_info "Prüfe Bind-Adresse (muss 0.0.0.0:${WEB_PORT} sein) …"
  local bind_line
  bind_line="$(ss -tlnp 2>/dev/null | grep ":${WEB_PORT} " || true)"
  if [[ -z "$bind_line" ]]; then
    ss -tlnp || true
    die "Kein Listener auf Port ${WEB_PORT} gefunden!"
  fi
  if echo "$bind_line" | grep -q "127.0.0.1:${WEB_PORT}"; then
    echo "$bind_line"
    die "Dienst lauscht nur auf 127.0.0.1 -> von außerhalb NICHT erreichbar!"
  fi
  msg_ok "Dienst lauscht korrekt: $(echo "$bind_line" | awk '{print $4}')"

  # Firewall: Debian-Standard im LXC hat keine nftables-Regeln, aber falls
  # ufw aktiv ist, den Port freigeben (idempotent).
  if have ufw; then
    ufw allow "${WEB_PORT}/tcp" >/dev/null 2>&1 || true
    msg_ok "ufw: Port ${WEB_PORT}/tcp freigegeben (falls aktiv)."
  fi
}

print_guest_summary() {
  local ip="${CT_IP:-127.0.0.1}"
  cat <<SUMMARY

==========================================================
  ${APP_NAME} wurde erfolgreich installiert ✔
==========================================================
  Web-UI      :  http://${ip}:${WEB_PORT}
  Login       :  Passwort '${ADMIN_PASSWORD}' (bitte ändern!)
  Broker-DB   :  770+ Broker vorgeladen (eraser-MIT-Seed + EU-Kuratierung)
  Container   :  unprivileged LXC, onboot=1
  Daten       :  /var/lib/brokershield (SQLite-DB, überlebt Updates)
  Einstellungen: /etc/brokershield/brokershield.env (Ollama/SMTP/Passwort)
  Dienst      :  systemctl status brokershield
  Logs        :  ${GUEST_LOG_FILE} · journalctl -u brokershield

  Update      :  Einzeiler auf dem Proxmox-Host erneut ausführen
  Deinstall   :  ./brokershield.sh --uninstall
==========================================================

SUMMARY
}

guest_main() {
  msg_info "${APP_NAME} – Gast-Phase (MODE=${MODE}) auf $(hostname), Start: $(date -Is)."
  [[ $EUID -eq 0 ]] || die "Gast-Phase muss als root laufen."
  apt_install ca-certificates curl jq git 2>/dev/null \
    || DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl jq git

  install_app
  verify_service_and_web

  print_guest_summary
}

#==============================
# HOST-PHASE: Proxmox-Node
#==============================
check_host_prereqs() {
  [[ $EUID -eq 0 ]] || die "Bitte als root auf dem Proxmox-Host ausführen (sudo su -)."
  [[ -d /etc/pve ]] || die "Dies ist kein Proxmox-VE-Host (/etc/pve fehlt). Script auf dem PVE-Node starten."
  local cmd
  for cmd in pct pvesm pveam pvesh curl openssl jq; do
    have "$cmd" || die "Benötigtes Werkzeug nicht gefunden: $cmd – nur auf Proxmox VE ausführen."
  done
}

check_upstream_reachable() {
  if [[ -z "${UPSTREAM_REPO//[A-Za-z0-9_.-]/}" && "$UPSTREAM_REPO" != */* ]]; then
    die "UPSTREAM_REPO fehlt oder hat kein USER/REPO-Format (ist: '${UPSTREAM_REPO}')."
  fi
  if ! curl -fsSL --max-time 15 --retry 2 "https://github.com/${UPSTREAM_REPO}" -o /dev/null; then
    die "Repo ${UPSTREAM_REPO} nicht erreichbar – URL im Installer (UPSTREAM_REPO) korrekt?"
  fi
  msg_ok "Upstream-Repo erreichbar: https://github.com/${UPSTREAM_REPO}"
}

find_ct_by_name() {
  local vmid hostname
  while read -r vmid; do
    hostname="$(pct config "$vmid" 2>/dev/null | awk '/^hostname:/{print $2}')"
    if [[ "$hostname" == "$APP_ID" ]]; then
      printf '%s\n' "$vmid"
    fi
  done < <(pct list 2>/dev/null | awk 'NR>1{print $1}')
}

next_free_ctid() {
  pvesh get /cluster/nextid 2>/dev/null || printf '999\n'
}

storage_rootdir_list() {
  local json=""
  json="$(pvesm status -content rootdir --output-format json 2>/dev/null || true)"
  if [[ -n "$json" ]] && printf '%s' "$json" | jq -e . >/dev/null 2>&1; then
    printf '%s' "$json" | jq -r '
      .[]
      | select(.active == 1)
      | select(((.content // "") | tostring) | contains("rootdir"))
      | [(.storage // .name), (.avail // 0)]
      | @tsv'
    return 0
  fi
  pvesm status -content rootdir 2>/dev/null | awk '
    NR > 1 && $3 == "active" && NF >= 6 {
      n++; names[n] = $1; avail[n] = $6 + 0
      if (avail[n] > max) max = avail[n]
    }
    END {
      mult = (max >= 8589934592) ? 1 : 1024
      for (i = 1; i <= n; i++) printf "%s\t%d\n", names[i], avail[i] * mult
    }'
}

fmt_gib() { awk -v b="$1" 'BEGIN { printf "%.1f", b / 1073741824 }'; }

storage_avail_bytes() { # storage_avail_bytes <Name>
  storage_rootdir_list | awk -v s="$1" '$1 == s { print $2; found = 1 } END { exit !found }'
}

select_storage() {
  local -a names=() frees=()
  local name avail

  if [[ -n "$STORAGE" ]] && storage_avail_bytes "$STORAGE" >/dev/null; then
    msg_info "Storage per Env vorgegeben und gültig: ${STORAGE}"
    return 0
  fi
  [[ -z "$STORAGE" ]] || msg_warn "Vorgegebener STORAGE '${STORAGE}' ist nicht aktiv – wähle neu."
  STORAGE=""

  while IFS=$'\t' read -r name avail; do
    names+=("$name")
    frees+=("$avail")
  done < <(storage_rootdir_list)

  ((${#names[@]})) || die "Kein aktiver Storage mit Inhaltstyp 'rootdir' gefunden."

  if (( ${#names[@]} == 1 )) || [[ ! -t 0 ]]; then
    local best=0 i
    for i in "${!frees[@]}"; do
      (( ${frees[$i]} > ${frees[$best]} )) && best=$i
    done
    STORAGE="${names[$best]}"
    msg_info "Storage automatisch gewählt: ${STORAGE}"
    return 0
  fi

  local i choice
  msg_info "Verfügbare Storages (rootdir):"
  for i in "${!names[@]}"; do
    printf '  %2d) %-20s frei: %s GB\n' "$((i+1))" "${names[$i]}" "$(fmt_gib "${frees[$i]}")" >&2
  done
  choice="$(ask_default "Welchen Storage verwenden?" "1")"
  if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#names[@]} )); then
    STORAGE="${names[$((choice-1))]}"
  else
    die "Ungültige Storage-Auswahl: ${choice}"
  fi
}

ensure_capacity() {
  local need_bytes=$(( VAR_DISK * 1073741824 ))
  local avail_bytes
  avail_bytes="$(storage_avail_bytes "$STORAGE" 2>/dev/null || true)"
  [[ -n "$avail_bytes" ]] || { msg_warn "Freier Speicher nicht ermittelbar – Kapazitätscheck übersprungen."; return 0; }
  if (( avail_bytes < need_bytes )); then
    die "Storage '${STORAGE}' hat nur $(fmt_gib "$avail_bytes") GB frei – ${VAR_DISK} GB angefordert."
  fi
  msg_ok "Kapazität ausreichend: $(fmt_gib "$avail_bytes") GB frei ≥ ${VAR_DISK} GB."
}

ensure_debian_template() {
  local tmpl
  msg_info "Suche neuestes ${VAR_OS}-${VAR_VERSION}-Standard-Template …"
  pveam update >/dev/null 2>&1 || true
  tmpl="$(pveam available --section system 2>/dev/null | awk '/debian-13-standard/{print $2}' | sort -rV | head -n1)"
  [[ -n "$tmpl" ]] || die "Kein debian-13-Template gefunden ('pveam available' manuell prüfen)."
  if ! pveam list local 2>/dev/null | grep -qF "local:vztmpl/${tmpl}"; then
    msg_info "Lade Template herunter: ${tmpl} …"
    pveam download local "$tmpl"
  else
    msg_info "Template bereits vorhanden: ${tmpl}"
  fi
  TEMPLATE="$tmpl"
}

validate_settings() {
  if ! [[ "$WEB_PORT" =~ ^[0-9]+$ ]] || (( WEB_PORT < 1024 || WEB_PORT > 65535 )); then
    die "WEB_PORT muss zwischen 1024 und 65535 liegen (ist: ${WEB_PORT})."
  fi
  [[ "$NET_MODE" == "dhcp" || "$NET_MODE" == "static" ]] || die "NET_MODE muss 'dhcp' oder 'static' sein."
}

resolve_self() {
  local cand="${BASH_SOURCE[0]:-}"
  if [[ -z "$cand" || "$cand" == "bash" || ! -f "$cand" || ! -r "$cand" ]]; then
    cand="$0"
  fi
  if [[ -f "$cand" && -r "$cand" && "$(head -c 2 "$cand" 2>/dev/null)" == "#!" ]]; then
    readlink -f "$cand"
    return 0
  fi
  msg_warn "Script wurde gepipe't – lade Kopie für den Container-Transfer …"
  fetch_to "$SCRIPT_URL" "${TMPDIR_INSTALL}/${APP_ID}-install.sh"
  local path
  path="$(readlink -f "${TMPDIR_INSTALL}/${APP_ID}-install.sh")"
  [[ -s "$path" ]] || die "Heruntergeladene Installer-Kopie fehlt/ist leer: ${path}"
  printf '%s\n' "$path"
}

create_container() {
  msg_info "Erstelle LXC ${APP_ID} (ID ${CTID}, ${VAR_CPU} vCPU / ${VAR_RAM} MB RAM / ${VAR_DISK} GB Disk, unprivileged) …"
  local ct_password
  ct_password="$(openssl rand -hex 8)"
  local tz_args=()
  if [[ -n "${TIMEZONE_OVERRIDE:-}" ]]; then
    tz_args=(--timezone "$TIMEZONE_OVERRIDE")
  elif [[ -r /etc/timezone ]]; then
    tz_args=(--timezone "$(tr -d '[:space:]' </etc/timezone)")
  fi

  pct create "$CTID" "local:vztmpl/${TEMPLATE}" \
    --hostname "$APP_ID" \
    --password "$ct_password" \
    --unprivileged "$CT_TYPE" \
    --cores "$VAR_CPU" \
    --memory "$VAR_RAM" \
    --swap "$VAR_SWAP" \
    --rootfs "${STORAGE}:${VAR_DISK}" \
    --net0 "name=eth0,bridge=${BRIDGE},${NET_CFG},firewall=0" \
    --onboot 1 \
    --tags "community-scripts,${APP_ID}" \
    --description "${APP_NAME} – Datenbroker-Lösch-Dashboard. Web-UI: http://<CT-IP>:${WEB_PORT} · Installer: bash -c \$(wget -qLO - ${SCRIPT_URL})" \
    "${tz_args[@]+"${tz_args[@]}"}" \
    --start 1

  msg_ok "Container erstellt (Konsolen-Passwort einmalig: ${ct_password} – ändern oder 'pct enter ${CTID}' nutzen)."
}

wait_for_ct_ip() {
  local attempts=45 ip="" i
  msg_info "Warte auf Netzwerk im Container …"
  for ((i = 1; i <= attempts; i++)); do
    ip="$(pct exec "$CTID" -- sh -c 'hostname -I 2>/dev/null' 2>/dev/null | awk '{print $1}' || true)"
    if [[ -n "$ip" ]]; then
      break
    fi
    sleep 2
  done
  [[ -n "$ip" ]] || die "Container hat keine IP erhalten (DHCP/Netzwerk prüfen: pct enter ${CTID})."
  CT_IP="$ip"
  msg_ok "Container-IP: ${CT_IP}"
}

run_guest_phase() {
  local self_path
  self_path="$(resolve_self)"
  [[ "$self_path" != *$'\n'* && -s "$self_path" ]] ||
    die "Interner Fehler: Installer-Pfad ungültig (${self_path@Q})."

  msg_info "Übertrage Installer in den Container …"
  pct push "$CTID" "$self_path" "/root/${APP_ID}-install.sh" >/dev/null
  pct exec "$CTID" -- test -s "/root/${APP_ID}-install.sh" ||
    die "Installer nach pct push im Container nicht vorhanden/leer."

  msg_info "Führe Gast-Installation aus (Log im Container: tail -f ${GUEST_LOG_FILE}) …"
  if ! pct exec "$CTID" -- env \
      BS_PHASE=guest \
      MODE="$MODE" \
      WEB_PORT="$WEB_PORT" \
      ADMIN_PASSWORD="$ADMIN_PASSWORD" \
      UPSTREAM_REPO="$UPSTREAM_REPO" \
      CT_IP="${CT_IP:-}" \
      DEBUG="$DEBUG" \
      DEBIAN_FRONTEND=noninteractive \
      LC_ALL=C.UTF-8 LANG=C.UTF-8 \
      bash "/root/${APP_ID}-install.sh"; then
    msg_error "Gast-Phase fehlgeschlagen – Container-Logauszug:"
    pct exec "$CTID" -- tail -n 80 "$GUEST_LOG_FILE" 2>/dev/null || true
    die "Installation im Container fehlgeschlagen (siehe Auszug oben sowie $LOG_FILE)."
  fi
}

do_uninstall() {
  local target="${TARGET_CTID}"
  if [[ -z "$target" ]]; then
    target="$(find_ct_by_name | head -n1 || true)"
  fi
  [[ -n "$target" ]] || die "Kein ${APP_NAME}-Container gefunden (pct list)."
  msg_warn "Deinstalliert ${APP_NAME} inklusive ALLER Daten (Profile, Anfragen-Historie!) aus CT ${target}!"
  confirm_or_die "Wirklich löschen? (pct stop + pct destroy ${target})"
  pct stop "$target" >/dev/null 2>&1 || true
  pct destroy --purge "$target"
  msg_ok "Container ${target} entfernt."
}

show_help() {
  cat <<HELP
${APP_NAME} – Proxmox-Installer (Community-Scripts-Stil)

Aufruf:
  bash brokershield.sh [Optionen]

Optionen:
  --update       Neuester Stand im vorhandenen Container
  --uninstall    Container inkl. Daten entfernen (interaktive Bestätigung)
  --ctid N       Vorhandene/vorgesehene CT-ID verwenden
  --port N       Web-UI-Port (Default: ${WEB_PORT})
  --debug        Volles bash -x-Tracing
  -h | --help    Diese Hilfe

Env-Variablen (Auswahl): CTID VAR_DISK VAR_CPU VAR_RAM BRIDGE NET_MODE
  NET_CIDR NET_GW WEB_PORT ADMIN_PASSWORD STORAGE DEBUG
  (Defaults stehen im Kopfteil des Scripts.)

Hinweis: BrokerShield ist leichtgewichtig (FastAPI+SQLite) – Standard-
Ressourcen (2 vCPU / 2 GB RAM / 8 GB Disk) reichen komfortabel.
Ollama läuft bewusst extern (BROKERSHIELD_OLLAMA_URL in der UI setzen).
HELP
}

parse_args() {
  while (($#)); do
    case "$1" in
      --update) MODE="update" ;;
      --uninstall) MODE="uninstall" ;;
      --debug) DEBUG=1; enable_debug ;;
      --ctid) TARGET_CTID="$(ask_required_value "$1" "${2:-}")"; shift ;;
      --port) WEB_PORT="$(ask_required_value "$1" "${2:-}")"; shift ;;
      -h|--help) show_help; exit 0 ;;
      *) die "Unbekannte Option: $1 (--help anzeigen)" ;;
    esac
    shift
  done
}

host_main() {
  parse_args "$@"
  check_host_prereqs
  validate_settings
  check_upstream_reachable

  if [[ "$MODE" == "uninstall" ]]; then
    do_uninstall
    return 0
  fi

  cat <<BANNER
  ____  ____  _   _ ____    _____ _   _  ____ ___ ____ _____ ____
 | __ )|  _ \| | | |  _ \  | ____| | | |/ ___|_ _/ ___| ____|  _ \
 |  _ \| |_) | | | | |_) | |  _| | |_| | |  _ | |\___ \  _| | |_) |
 | |_) |  _ <| |_| |  _ <  | |___|  _  | |_| || | ___) | |___|  _ <
 |____/|_| \_\\___/|_| \_\ |_____|_| |_|\____|___|____/|_____|_| \_\

  BrokerShield – Proxmox-LXC-Installer (Community-Scripts-Stil)
  Digitale Souveränität: 770+ Datenbroker im Blick behalten
BANNER

  # Existierenden Container erkennen → idempotent in den Update-Pfad schwenken
  local existing
  existing="$(find_ct_by_name | head -n1 || true)"
  if [[ -n "${TARGET_CTID}" ]]; then
    CTID="$TARGET_CTID"
    if [[ -n "$existing" && "$existing" != "$CTID" ]]; then
      msg_warn "Gefundener ${APP_ID}-Container hat ID ${existing}, gewünscht ist ${CTID}."
    fi
  elif [[ -n "$existing" ]]; then
    CTID="$existing"
  fi

  if [[ -n "$existing" && "$MODE" == "install" ]]; then
    MODE="update"
    msg_info "Vorhandener Container erkannt (ID ${existing}) – wechsle in den Update-Modus."
  fi

  if [[ "$MODE" == "update" ]]; then
    CTID="${CTID:?Keine CT-ID für Update ermittelbar (--ctid angeben)}"
    pct status "$CTID" >/dev/null 2>&1 || die "CT ${CTID} nicht gefunden (pct list)."
    if [[ "$(pct status "$CTID" | awk '{print $2}')" != "running" ]]; then
      msg_info "Starte gestoppten Container ${CTID} …"
      pct start "$CTID"
    fi
    wait_for_ct_ip
    run_guest_phase
    msg_ok "Update abgeschlossen → http://${CT_IP}:${WEB_PORT}"
    return 0
  fi

  # Frische Installation: Parameter erfragen
  CTID="${CTID:-$(next_free_ctid)}"
  CTID="$(ask_default "CT-ID" "$CTID")"
  [[ "$CTID" =~ ^[0-9]+$ ]] || die "Ungültige CT-ID: ${CTID}"
  if pct status "$CTID" >/dev/null 2>&1; then
    die "CT-ID ${CTID} ist bereits vergeben (pct list)."
  fi
  select_storage
  ensure_debian_template

  if [[ "$NET_MODE" == "static" ]]; then
    [[ -n "$NET_CIDR" && -n "$NET_GW" ]] || die "NET_MODE=static benötigt NET_CIDR und NET_GW."
    NET_CFG="ip=${NET_CIDR},gw=${NET_GW}"
  fi

  VAR_DISK="$(ask_default "Disk (GB)" "$VAR_DISK")"
  VAR_CPU="$(ask_default "vCPU-Kerne" "$VAR_CPU")"
  VAR_RAM="$(ask_default "RAM (MB)" "$VAR_RAM")"

  ensure_capacity
  create_container
  wait_for_ct_ip
  run_guest_phase

  # Verifikation von außen (vom Proxmox-Host aus)
  msg_info "Verifikation von außen: ${APP_NAME} wirklich erreichbar?"
  local external_ok=0 http_code="" curl_rc=0 health_url="http://${CT_IP}:${WEB_PORT}/healthz"
  local attempt
  for attempt in 1 2 3 4 5; do
    http_code="$(curl --noproxy '*' -s -m 5 -o /dev/null -w '%{http_code}' "$health_url" 2>/dev/null)"
    curl_rc=$?
    if [[ "$http_code" == "200" ]]; then
      external_ok=1
      break
    fi
    sleep 2
  done

  cat <<SUCCESS

========================================================================
  Installation abgeschlossen ✔  —  Deine Daten. Deine Hoheit.
------------------------------------------------------------------------
  Web-UI   :  http://${CT_IP}:${WEB_PORT}
  Login    :  Passwort '${ADMIN_PASSWORD}' (bitte sofort ändern!)
  Container:  ${APP_ID} (ID ${CTID}, unprivileged, onboot=1)
  Einstieg :  pct enter ${CTID}
  Update   :  Einzeiler erneut ausführen (erkennt den Container automatisch)
  Deinstall:  bash brokershield.sh --uninstall
========================================================================

SUCCESS

  if (( external_ok == 0 )); then
    msg_warn "Web-UI war vom Host aus nach ${attempt} Versuchen noch nicht erreichbar"
    msg_warn "(letzter HTTP-Code: ${http_code:-keiner}, curl-rc: ${curl_rc})."
    msg_warn "Diagnose:"
    msg_warn "  pct exec ${CTID} -- systemctl status brokershield"
    msg_warn "  pct exec ${CTID} -- journalctl -u brokershield -n 60 --no-pager"
    msg_warn "  pct exec ${CTID} -- ss -tlnp | grep ${WEB_PORT}"
    exit 1
  fi
  msg_ok "Web-UI vom Host aus erreichbar (HTTP 200)."
}

#==============================
# Einstiegspunkt
#==============================
if [[ "$PHASE" == "guest" ]]; then
  exec > >(tee -a "$GUEST_LOG_FILE") 2>&1
  guest_main
else
  SCRIPT_URL="${SCRIPT_URL:-https://raw.githubusercontent.com/HatchetMan111/DataBrokerShield/main/install/brokershield.sh}"
  host_main "$@"
fi
