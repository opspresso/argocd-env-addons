#!/bin/bash
# Apply versions recorded by update_versions.py to local wrapper charts.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
VERSIONS_FILE="${ROOT_DIR}/config/versions.json"
DRY_RUN=false
CHART=""
WORK_FILE=""
trap 'if [ -n "${WORK_FILE}" ]; then rm -f -- "${WORK_FILE}"; fi' EXIT

usage() {
  echo "Usage: $0 [--chart NAME] [--dry-run]"
}

die() {
  echo "Error: $*" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -c|--chart)
      [ "$#" -ge 2 ] && [ -n "$2" ] || die "$1 requires a chart name"
      CHART=$2
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "unknown argument: $1"
      ;;
  esac
done

command -v jq >/dev/null || die "jq is required"
command -v yq >/dev/null || die "yq v4 is required"
[ -f "${VERSIONS_FILE}" ] || die "missing ${VERSIONS_FILE}"

# A chart can be selected by its config key, local directory, or upstream name.
entries=$(jq -er --arg chart "${CHART}" '
  .versions | to_entries
  | if $chart == "" then . else
      map(select(.key == $chart or (.value.path // .key) == $chart
        or (.value.chart | split("/")[-1]) == $chart))
    end
  | if length == 0 then error("chart not found: " + $chart) else .[] end
  | [.key, (.value.path // .key), (.value.chart // "" | split("/")[-1]),
     (.value.version // ""),
     (.value.current // ""), (.value.locked // false),
     (.value.disabled // false)] | join("|")
' "${VERSIONS_FILE}") || die "could not read chart versions"

files=()
olds=()
news=()
line_sets=()

# Check every candidate before writing any Chart.yaml.
while IFS='|' read -r key path upstream latest cached locked disabled; do
  case "${path}" in
    ""|*[!a-zA-Z0-9_-]*) die "invalid chart path for ${key}: ${path}" ;;
  esac

  if [ "${locked}" = true ] || [ "${disabled}" = true ]; then
    echo "Skipping ${key}: locked or disabled"
    continue
  fi

  file="${ROOT_DIR}/charts/${path}/Chart.yaml"
  if [ ! -f "${file}" ]; then
    echo "Skipping ${key}: ${file} does not exist"
    continue
  fi

  [[ "${latest}" =~ ^v?[0-9][a-zA-Z0-9.+-]*$ ]] || die "invalid latest version for ${key}: ${latest}"
  current=$(yq -r '.version // ""' "${file}") || die "could not read ${file}"
  [ -n "${current}" ] || die "missing version in ${file}"
  if [ "${current}" = "${latest}" ]; then
    echo "Unchanged ${key}: ${current}"
    continue
  fi
  if [ -n "${cached}" ] && [ "${cached}" != "${current}" ]; then
    die "${key}: recorded current ${cached} differs from Chart.yaml ${current}; run update_versions.py first"
  fi

  dependencies=$(yq -r '(.dependencies // []) | length' "${file}") || die "could not inspect ${file}"
  upstream_repo=""
  if [ "${dependencies}" -gt 0 ]; then
    upstream_repo=$(UPSTREAM_NAME="${upstream}" yq -r '
      (.dependencies // [])[] | select(.name == strenv(UPSTREAM_NAME)) | .repository
    ' "${file}") || die "could not inspect ${file}"
    [ -n "${upstream_repo}" ] && [ "${upstream_repo}" != null ] \
      && [[ "${upstream_repo}" != *$'\n'* ]] \
      || die "${key}: expected one ${upstream} dependency in ${file}"
  fi

  lines=$(OLD_VERSION="${current}" UPSTREAM_REPO="${upstream_repo}" yq -r '
    (.version | line),
    ((.dependencies // [])[]
      | select(.repository == strenv(UPSTREAM_REPO) and .version == strenv(OLD_VERSION))
      | .version | line)
  ' "${file}") || die "could not inspect ${file}"
  [ -n "${lines}" ] || die "missing version line in ${file}"
  if [ "${dependencies}" -gt 0 ] && [[ "${lines}" != *$'\n'* ]]; then
    die "${key}: no dependency matches wrapper version ${current}"
  fi

  files+=("${file}")
  olds+=("${current}")
  news+=("${latest}")
  line_sets+=("${lines//$'\n'/,}")
done <<< "${entries}"

for ((i = 0; i < ${#files[@]}; i++)); do
  file=${files[i]}
  old=${olds[i]}
  new=${news[i]}
  echo "Updating ${file#${ROOT_DIR}/}: ${old} -> ${new}$([ "${DRY_RUN}" = true ] && echo ' (dry run)')"
  if [ "${DRY_RUN}" = true ]; then
    continue
  fi

  WORK_FILE=$(mktemp "${file}.tmp.XXXXXX")
  cp -p "${file}" "${WORK_FILE}"
  awk -v old="${old}" -v new="${new}" -v lines="${line_sets[i]}" '
    BEGIN {
      count = split(lines, numbers, ",")
      for (i = 1; i <= count; i++) selected[numbers[i]] = 1
    }
    selected[NR] {
      if ($0 !~ /^[[:space:]]*version:[[:space:]]*/) {
        print "unexpected version line " NR > "/dev/stderr"
        exit 1
      }
      pos = index($0, ":") + 1
      while (substr($0, pos, 1) ~ /[[:space:]]/) pos++
      quote = substr($0, pos, 1)
      if (quote == "\"" || quote == "\047") pos++
      else quote = ""
      after = substr($0, pos + length(old), 1)
      if (substr($0, pos, length(old)) != old ||
          (quote != "" && after != quote) ||
          (quote == "" && after != "" && after !~ /[[:space:]#]/)) {
        print "unexpected version value on line " NR > "/dev/stderr"
        exit 1
      }
      $0 = substr($0, 1, pos - 1) new substr($0, pos + length(old))
      changed++
    }
    { print }
    END { if (changed != count) exit 1 }
  ' "${file}" > "${WORK_FILE}" || die "could not update ${file}"

  NEW_VERSION="${new}" yq -e '.version == strenv(NEW_VERSION)' "${WORK_FILE}" >/dev/null \
    || die "invalid updated chart: ${file}"
  mv "${WORK_FILE}" "${file}"
  WORK_FILE=""
done

if [ "${DRY_RUN}" = true ]; then
  echo "Charts to update: ${#files[@]}"
else
  echo "Charts updated: ${#files[@]}"
fi
