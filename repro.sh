#!/bin/bash
# Reproduce the Zenodo REST API HTTP 500 on BibTeX content negotiation.
#
# GET /api/records (the search/list endpoint) returns 500 when
# `Accept: application/x-bibtex` is requested, while GET /api/records/:id
# serves the same media type correctly. See docs/zenodo-api-bibtex-500.md.
#
# Usage:
#   ZENODO_TOKEN=<token> ./repro.sh [orcid]
#
# Requires: curl, jq. Exits 0 when the 500 reproduces, 1 when it does not.

set -euo pipefail

API=https://zenodo.org/api/records
ORCID=${1:-0000-0002-6533-164X}
STAMP=zenodo.stamp

if [[ -z ${ZENODO_TOKEN:-} ]]; then
  echo "error: ZENODO_TOKEN is unset." >&2
  echo "Create a token at https://zenodo.org/account/settings/applications/" >&2
  echo "then export it — do not hard-code it in this file." >&2
  exit 2
fi

# Pass the token via a curl config file rather than -H, so it never appears in
# the process table or in a shell trace.
zenodo_curl() {
  curl --silent --show-error \
    --config <(printf 'header = "Authorization: Bearer %s"\n' "$ZENODO_TOKEN") \
    "$@"
}

echo "1. Resolving ORCID $ORCID to a result count (Accept: application/json)"
zenodo_curl "$API?q=creators.orcid:${ORCID}&size=1&sort=publication_date" |
  jq '[.hits.hits[0].updated, .hits.total]' >"$STAMP"

SIZE=$(jq '.[1]' "$STAMP")
echo "   $SIZE record(s); stamp written to $STAMP"

echo "2. Requesting all $SIZE record(s) as BibTeX (Accept: application/x-bibtex)"
body=$(mktemp)
trap 'rm -f "$body"' EXIT
status=$(
  zenodo_curl --output "$body" --write-out '%{http_code}' \
    --header 'Accept: application/x-bibtex' \
    "$API?q=creators.orcid:${ORCID}&size=${SIZE}"
)

echo "   HTTP $status"
cat "$body"
echo

if [[ $status == 500 ]]; then
  echo "REPRODUCED: list endpoint 500s on application/x-bibtex."
  exit 0
fi

echo "NOT REPRODUCED: expected HTTP 500, got $status. Upstream may be fixed." >&2
exit 1
