#!/bin/sh
# Sourced by sync.sh after Nexus authentication is configured. Only 404 means absent.
set -eu
set -o pipefail
: "${NEXUS_PUBLISHER_PASSWORD:?publisher password is required}"
: "${NEXUS_READER_PASSWORD:?reader password is required}"
: "${NEXUS_CLEANER_PASSWORD:?cleaner password is required}"
umask 077
delivery_tmp=$(mktemp -d)
trap 'rm -rf "$delivery_tmp"' EXIT HUP INT TERM

read_delivery() {
  delivery_status=$(curl -sS -u "admin:${NEXUS_ADMIN_PASSWORD}" -o "$delivery_tmp/have.json" \
    -w '%{http_code}' "$B/v1/$1")
  case "$delivery_status" in
    200) return 0 ;;
    404) return 1 ;;
    *) echo "Nexus read failed: $1 HTTP $delivery_status" >&2; exit 1 ;;
  esac
}

# The caller supplies the exact managed fields. Unrelated repository fields remain untouched.
ensure_delivery() {
  delivery_collection=$1 delivery_name=$2
  cat > "$delivery_tmp/want.json"
  if read_delivery "$delivery_collection/$delivery_name"; then
    if ! jq -e --slurpfile want "$delivery_tmp/want.json" 'if has("privileges") then .privileges == $want[0].privileges and .roles == $want[0].roles else contains($want[0]) end' "$delivery_tmp/have.json" >/dev/null; then
      jq -s '.[0] * .[1]' "$delivery_tmp/have.json" "$delivery_tmp/want.json" \
        | api -X PUT "$B/v1/$delivery_collection/$delivery_name" -d @- -o /dev/null
    fi
  else
    api -X POST "$B/v1/$delivery_collection" -d @"$delivery_tmp/want.json" -o /dev/null
  fi
}

# Preserve anonymous access to the installation's existing public packages, not private app artifacts.
api "$B/v1/repositories" | jq --argjson names "$NEXUS_PUBLIC_REPOSITORIES" \
  '{id:"public-packages",name:"Public packages",description:"Anonymous reads of configured package repositories",roles:[],
    privileges:[.[] | select(.name as $name | $names | index($name)) |
      "nx-repository-view-\(.format)-\(.name)-read", "nx-repository-view-\(.format)-\(.name)-browse"]}' \
  | ensure_delivery security/roles public-packages
api "$B/v1/security/users?source=default&userId=anonymous" | jq -e 'map(select(.userId=="anonymous")) | if length==1 then .[0] else error("anonymous user missing or ambiguous") end' > "$delivery_tmp/have.json"
jq '.roles=["public-packages"]' "$delivery_tmp/have.json" \
  | api -X PUT "$B/v1/security/users/anonymous" -d @- -o /dev/null

ensure_delivery repositories/raw/hosted runway-artifacts <<'JSON'
{"name":"runway-artifacts","online":true,"storage":{"blobStoreName":"default","strictContentTypeValidation":true,"writePolicy":"ALLOW_ONCE"}}
JSON
ensure_delivery repositories/docker/hosted runway-images <<'JSON'
{"name":"runway-images","online":true,"storage":{"blobStoreName":"default","strictContentTypeValidation":true,"writePolicy":"ALLOW_ONCE","latestPolicy":false},"docker":{"v1Enabled":false,"forceBasicAuth":true,"pathEnabled":true}}
JSON


for access in reader publisher cleaner; do
  jq -n --arg access "$access" \
    '{id:("runway-"+$access),name:("Runway "+$access),description:"Agent Runway artifacts only",roles:[],
      privileges:([["raw","runway-artifacts"],["docker","runway-images"]] | [.[] as $repo |
        (["read","browse"] + (if $access=="publisher" then ["add","edit"] elif $access=="cleaner" then ["delete"] else [] end))[] |
        "nx-repository-view-\($repo[0])-\($repo[1])-\(.)"])}' \
    | ensure_delivery security/roles "runway-$access"
  api "$B/v1/security/users?source=default&userId=runway-$access" \
    | jq --arg id "runway-$access" 'map(select(.userId==$id))' > "$delivery_tmp/users.json"
  if [ "$(jq length "$delivery_tmp/users.json")" = 0 ]; then
    jq -n --arg access "$access" \
      '{userId:("runway-"+$access),firstName:"Runway",lastName:$access,emailAddress:"runway@example.invalid",status:"active",
        roles:["runway-"+$access],password:(if $access=="publisher" then env.NEXUS_PUBLISHER_PASSWORD elif $access=="cleaner" then env.NEXUS_CLEANER_PASSWORD else env.NEXUS_READER_PASSWORD end)}' \
      | api -X POST "$B/v1/security/users" -d @- -o /dev/null
  else
    jq -e --arg role "runway-$access" 'if length==1 then .[0] | .roles=[$role] | .status="active" else error("ambiguous user") end' "$delivery_tmp/users.json" \
      | api -X PUT "$B/v1/security/users/runway-$access" -d @- -o /dev/null
  fi
done
echo 'Runway repositories and scoped accounts synchronized'
